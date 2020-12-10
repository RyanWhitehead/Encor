##Ryan Whitehead
##11/27/2020
##This is the script that will listen for webhooks. Each webhook is represented
##by a speciifc function and a specific route.

## TODO
##     -get the post urls for updating status
##
##     -If someone is hired, add them to paylocity
##
##     -Retry logic
##
##     -error handling
##
##     -if I were to run this for a month the brezzy thing would loose auth
##
##     -Think about exporting to an excel for reporting
##
##     -Log errors to a csv
##
##     -Get this to run on reboot


from flask import Flask, request, Response, json
import header
import requests, boto3, json
from datetime import datetime

app = Flask(__name__)

app.env = 'development'

sign_in = {"email":header.get_secret('breezy_email'),'password':header.get_secret('breezy_password')}
breezy_auth = requests.post('https://api.breezy.hr/v3/signin',data=sign_in).json()['access_token']
breezy_header = {'Authorization':breezy_auth}
breezy_company_id = header.get_secret('breezy_company_id')

acuity_user_id = header.get_secret('acuity_user_id')
acuity_api_key = header.get_secret('acuity_api_key')

ricochet_post_token = header.get_secret('ricochet_post_token')

#TODO
# -Add the appointment id to the csv

#this is the fucntion that fires everytime an interview is scheduled. all it needs to do is update the breezy
#stage id to 'Interviewing'. this is so that we know not to text the candidate again.
@app.route('/interviewScheduled', methods=['POST'])
def interviewScheduled():
    #try:
    if request.form['action'] == 'scheduled' or request.form['action'] == 'rescheduled':
        acuity = requests.get("https://acuityscheduling.com/api/v1/appointments/"+request.form['id'], auth=(acuity_user_id,acuity_api_key))
        for i in acuity.json()['forms']: #Note: the order these come in is soonest to latesest, that menas the appointment id is the latest
            if i['name'] == "Candidate Id":
                candidate_id = i['values'][0]['value']

        position_id = header.find_file(candidate_id)[0][1]
        lead_id = header.find_file(candidate_id)[0][2]

        if request.form['action'] == 'rescheduled':
            header.addCustom(candidate_id,position_id,'Has Rescheduled','True')
            #change the appointment dispostiion back to nil
            empty_disposition = json.dumps({"feilds":[{"id":8806210,"value":""}]})
            r = requests.put("https://acuityscheduling.com/api/v1/appointments/"+request.form['id'], data=empty_disposition, auth=(acuity_user_id,acuity_api_key))
            header.jprint(r.json())
            
        #update breezy stage
        header.updateStage(candidate_id,position_id,header.Interviewing)
        header.addCustom(candidate_id,position_id,'appointment_id',request.form['id'])
        #update ricochet status
        header.updateStatus(lead_id,header.interview_scheduled)
        header.update_appointment(candidate_id, request.form['id'])
        return Response(status=200)

    else:
        return Response(status=201)

    #except UnboundLocalError or KeyError:
       # print("Someone is missing necassary information")
       # return Response(status=401)

   # except IndexError:
        #print("There is some issue finding a candidate in the csv")
       # return Response(status=501)

app.add_url_rule('/interviewRescheduled', 'interviewScheduled', interviewScheduled, methods=['POST'])

#TODO
# -Make the info actually imported into ricochet more than just name and numebr

#this is the function that fires everytime a candiate is added into breezy. This is the starting off point for the whole
#automated system. It should first get the candidate, then add them as a lead in ricochet, it should then get the id for
#the lead we just created. After that it should creat a link with all of their info, including there candidate id from
#breezy. I should save that link to breezy, and send them a text with that link fot them to be able to schedule and interview
#Then it will save the time of the text in breezy, as well as how many texts have been sent, which should only be one. Lastly it
#adds a row in the csv file with the candidate id, position id, and the lead id, in that order.
@app.route('/candidateAdded', methods=['POST'])
def candidateAdded():
    try:
        candidate_id = request.json['object']['candidate']['_id']
        position_id = request.json['object']['position']['_id']
        breezy_candidate = header.get_candidate(candidate_id,position_id).json()
        
        first_name = request.json['object']['candidate']['name'].split()[0]
        last_name = request.json['object']['candidate']['name'].split()[-1]
        position = request.json['object']['position']['name']

        acuity_link = "https://encorsolar.as.me/?appointmentType=18537783&firstName="+first_name+"&lastName="+last_name+"&phone="+breezy_candidate['phone_number']+"&email="+breezy_candidate['email_address']
        
        #this block of text send the info to ricochet and adds a custom attribute that is the breezy id to search for later
        ricochet_lead_values = {
            'phone': breezy_candidate['phone_number'],
            "firstName": first_name,
            'lastName':last_name,
            'candidate_id':candidate_id,
            'acuity_link':acuity_link,
            'position':position,
            'status': "0. NEW"
            }
        
        ricochet_lead_id = requests.post('https://leads.ricochet.me/api/v1/lead/create/Breezy?token='+ricochet_post_token, data=ricochet_lead_values).json()["lead_id"]

        print(ricochet_lead_id)

        #this adds the custom url to the candidate
        header.addCustom(candidate_id,position_id,'Custom Link',acuity_link)

        #this code saves the candidate
        contacted_candidate = [[candidate_id,position_id,ricochet_lead_id,"appointment_id"]]
        header.add_file(contacted_candidate)
        
        header.updateStage(candidate_id,position_id,header.Texting)

        return Response(status=200)
        
    except KeyError or IndexError:
        print("Likely someone has put in an invlaid name")
        return Response(status=400)    

#TODO
# -Make sure to do it based on the new dispositions. Act accordingly

#this is the function that triggers when anything is changed on a acuity appointment. While we don't need to know every change,
#it is important to be able know when a disposition is change. In an ideal world, the disposition is only changed once, maybe twice
#it should only do things when the disposition is changed and this should only happen at the end of an interview.
@app.route('/dispositionChanged', methods=['POST'])
def dispositionChanged():
    try:
        #take the appointment and get the breezy id out of it
        hired = False
        change = True
        acuity = requests.get("https://acuityscheduling.com/api/v1/appointments/"+request.form['id'], auth=(acuity_user_id,acuity_api_key))

        for i in acuity.json()['forms']:

            if i['name'] == "Candidate Id":
                candidate_id = i['values'][0]['value']
            if i['name'] == "Interview Disposition":
                disposition = i['values'][0]['value']
        
        candidate_id = header.find_file(request.form['id'],3)[0][0]
        position_id = header.find_file(candidate_id)[0][1]
        lead_id = header.find_file(candidate_id)[0][2]
        
        print(candidate_id,position_id,disposition)
        if request.form['action'] == changed:
            #get the correct pipleine stage based off of the disposistion
            if disposition == "Offer Made - Accepted":
                stage = header.Onboarding
                hired = True
                
            elif disposition == "Offer Made - Not Accepted":
                stage = header.Disqualified
                header.delete_file(candidate_id)
                header.addCustom(candidate_id,position_id,'Discard Reason','Offer Made - Not Accepted')
                
            elif disposition == "Not Offered":
                stage = header.Disqualified
                header.delete_file(candidate_id)
                header.addCustom(candidate_id,position_id,'Discard Reason','Not Offered')


            #this needs to know a few things, did they schedule from a text or were they called (I can check this by seeing if they were in a contacted status previousely), if they were 
            # called, put them into noshow(owned) otherwise if they noshow an interview, and were never in a contact status put them in the noshow status. second, have they no 
            # showed an interview before, if they have and are doing it again, we need to update their breezy to disqaulifed as well as ricochet.
            elif disposition == "No Show": #this is a problem because of rescheduling
                no_show = False
                rescheduled = False
                stage = header.Interviewing
                for i in header.get_candidate(candidate_id,position_id).json()['custom_attributes']:
                    if i['name'] == 'No Show':
                        no_show = True
                        if i['value'] != request.form['id']:
                            header.addCustom(candidate_id,position_id,'No Show',request.form['id'])
                            header.updateStatus(lead_id,header.interview_dropped)
                            print('it did the thing')
                            change = False
                    if i['name'] == 'Has Rescheduled':
                        rescheduled = True
                if no_show and rescheduled: #if they have no showed before, and have reshceduled before
                    header.addCustom(candidate_id,position_id,'No Show',request.form['id'])
                    header.updateStatus(lead_id,header.interview_dropped)
                    print('it did the thing')
                    change = False
                    
                if no_show != True:
                    header.addCustom(candidate_id,position_id,'No Show',request.form['id'])
                    header.updateStatus(lead_id,header.interview_no_show)
                    stage = header.Interviewing
                    
            elif disposition == "" or disposition == "Pending":
                change = False

            #update breezy with the crroect pipleine stage
            if change:
                header.updateStage(candidate_id,position_id,stage)

            #if they have been offered and accepted
            if hired:
                print("Hired")
                header.updateStatus(lead_id,header.hired_ric)
                header.delete_file(candidate_id)
                
            return Response(status=200)
        else:
            return Response(status=201)
    except UnboundLocalError or KeyError:
        print("Someone is missing necassary information")
        return Response(status=401)
    except IndexError:
        print("There is some issue finding a candidate in the csv")
        return Response(status=501)
    

#TODO
# -Just keep this updated for when I need to do something

#this functino should trigger everytime a candidates dispostiion in ricochet changes. If we set this up the way I think we will
#this will tell me if theyve been contated and would like to be called back, or if they havnt been contacted
#This has now become, "everytime a status is changed, do something"
#I'm thinking that most of this automatino can be done in ricochet, but for reporting reason, it makes sense to have
#everything in here just in case
@app.route("/statusUpdated", methods=["POST"])
def statusUpdate():
    lead = request.json
    header.jprint(lead)

    lead_id = lead['id']
    candidate_id = header.find_file(lead_id,2)[0][0]
    position_id = header.find_file(lead_id,2)[0][1]

    print(candidate_id,position_id)
   
    if lead['status'] == "2. CONTACTED - Not Interested": #this is when we learn they are no longer interested over the phone
        header.unasign(lead)
        header.updateStatus(lead_id,header.disqualified_ric)

    elif lead['status'] == "2. CONTACTED - Wrong Numebr": #this is when they no show twice
        header.unasign(lead)
        header.updateStatus(lead_id,header.disqualified_ric)

    elif lead['status'] == "0. NEW - Dial": #this is when they are in theyve been texted twice
        header.updateStage(candidate_id,position_id,header.Dialing)
    
    header.addCustom(candidate_id,position_id,'Ricochet Status',lead['status'])
    
    return Response(status=200)

#this just runs the code on port 80, and will accept info form anyone (unofrtuantly this is necsassry
#to get the webhooks from the different sites.)
if __name__ == '__main__':
	app.run(port=80,host='0.0.0.0',debug=True)

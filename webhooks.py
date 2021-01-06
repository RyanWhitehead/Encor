##Ryan Whitehead
##11/27/2020
##This is the script that will listen for webhooks. Each webhook is represented
##by a speciifc function and a specific route.

## TODO
##     -If someone is hired, add them to paylocity, and update their breezy stage

from flask import Flask, request, Response, json
import header
import requests, boto3, json, tenacity, logging, sys
from datetime import datetime
from logging.handlers import RotatingFileHandler

#this code makes it so only werkzueg is logging, and creates a rotating file handler to make sure that afer 10 mbs there is a new file create
for name in ['boto', 'urllib3', 's3transfer', 'boto3', 'botocore', 'nose']:
    logging.getLogger(name).setLevel(logging.CRITICAL)

handler = RotatingFileHandler('/home/ubuntu/DEBUG.log', maxBytes=10*1024*1024, backupCount=2)#10 Mbs

logger = logging.getLogger('werkzeug')

logger.setLevel(logging.DEBUG)
logger.addHandler(handler)

#this creates the flask app
app = Flask(__name__)

#get all the sensitive info from the secrets manager in aws
sign_in = {"email":header.get_secret('breezy_email'),'password':header.get_secret('breezy_password')}
breezy_auth = requests.post('https://api.breezy.hr/v3/signin',data=sign_in).json()['access_token']
breezy_header = {'Authorization':breezy_auth}
breezy_company_id = header.get_secret('breezy_company_id')

acuity_user_id = header.get_secret('acuity_user_id')
acuity_api_key = header.get_secret('acuity_api_key')

ricochet_post_token = header.get_secret('ricochet_post_token')

#this is the fucntion that fires everytime an interview is scheduled. all it needs to do is update the breezy
#stage id to 'Interviewing'. this is so that we know not to text the candidate again.
@app.route('/interviewScheduled', methods=['POST'])
def interviewScheduled():
    try:
        #if the requrst is scheduled or reschedulued
        if request.form['action'] == 'scheduled' or request.form['action'] == 'rescheduled':
            #get the appointment info from acuity
            acuity = requests.get("https://acuityscheduling.com/api/v1/appointments/"+request.form['id'], auth=(acuity_user_id,acuity_api_key))
            #get the candidate Id from acuity
            for i in acuity.json()['forms']: #Note: the order these come in is soonest to latesest, that menas the appointment id is the latest
                if i['name'] == "Candidate Id":
                    candidate_id = i['values'][0]['value']

            #get the posisiton id and lead id from the csv using the candidate id
            position_id = header.find_file(candidate_id, '/home/ubuntu/uncontacted_candidates.csv')[0][1]
            lead_id = header.find_file(candidate_id, '/home/ubuntu/uncontacted_candidates.csv')[0][2]
            
            #if they reschedule, set the disposition back to null
            if request.form['action'] == 'rescheduled':
                header.addCustom(candidate_id,position_id,'Has Rescheduled','True')
                #change the appointment dispostiion back to nil
                empty_disposition = json.dumps({
                    'fields':[
                        {
                        "id":8806210,
                        'value':""
                        }
                    ]
                })
                requests.put("https://acuityscheduling.com/api/v1/appointments/"+request.form['id'], data=empty_disposition, auth=(acuity_user_id,acuity_api_key))
                
            #get the candidates info from the appointment id
            full_name = acuity.json()['firstName']+" "+acuity.json()['lastName']
            phone = acuity.json()['phone']
            email = acuity.json()['email']

            breezy_update_url = 'https://api.breezy.hr/v3/company/'+breezy_company_id+'/position/'+position_id+'/candidate/'+candidate_id
            
            #Update reporting with the information we now hve
            update = {
                'intScheduledon':datetime.now().date(),
                'intScheduledFor':acuity.json()['date'],
                'firstName':acuity.json()['firstName'],
                'lastName':acuity.json()['lastName'],
                'phone':phone,
                'email':email
            }

            header.updateReporting(candidate_id, update)

            #update breezy with the information just in case its changed
            update_info = {
                'name':full_name,
                'phone_number':phone,
                'email_address':email
            }
            requests.put(breezy_update_url, data=update_info, headers=breezy_header)
            #update ricochet with the information just in case its changed
            head = {
                "Content-Type":"application/json"
            }
            body = json.dumps({
                "token":header.get_secret('ricochet_user_token'),
                'stc_id':lead_id,
                'firstName':acuity.json()['firstName'],
                'lastName':acuity.json()['lastName'],
                'phone1':phone,
                'email':email
            })
            requests.post("https://ricochet.me/api/v4/leads/externalupdate", data=body, headers=head)

            #add some stuff to breezy and update their stage
            header.updateStage(candidate_id,position_id,'Interviewing')
            header.addCustom(candidate_id,position_id,'appointment_id',request.form['id'])
            #update ricochet status
            header.updateStatus(lead_id,header.contacted_interview)
            return Response(status=200)

        else:
            return Response(status=201)

    #check for didferent errors and log them.
    except UnboundLocalError:
        logger.error("Someone is missing necassary information")
        logger.exception("message")  
        return Response(status=401)

    except KeyError:
       logger.error("Someone is missing necassary information")
       logger.exception("message")  
       return Response(status=401)

    except IndexError:
        logger.error("There is some issue finding a candidate in the csv")
        logger.exception("message")  
        contacted_candidate = [[candidate_id,position_id,lead_id]]
        header.add_file(contacted_candidate,'/home/ubuntu/uncontacted_candidates.csv')
        return Response(status=501)

    except:
        logger.exception("message")  
        return Response(status=500)

#run this funciton even if its a reschedule
app.add_url_rule('/interviewRescheduled', 'interviewScheduled', interviewScheduled, methods=['POST'])


#this is the function that fires everytime a candiate is added into breezy. This is the starting off point for the whole
#automated system. It should first get the candidate, then add them as a lead in ricochet, it should then get the id for
#the lead we just created. After that it should creat a link with all of their info, including there candidate id from
#breezy. I should save that link to breezy, and send them a text with that link fot them to be able to schedule and interview
#Then it will save the time of the text in breezy, as well as how many texts have been sent, which should only be one. Lastly it
#adds a row in the csv file with the candidate id, position id, and the lead id, in that order.
@app.route('/candidateAdded', methods=['POST'])
def candidateAdded():
    try:
        #get some info from the webhook
        breezy_candidate = request.json['object']
        candidate_id = breezy_candidate['candidate']['_id']
        position_id = breezy_candidate['position']['_id']
        
        first_name = breezy_candidate['candidate']['name'].split()[0]
        last_name = breezy_candidate['candidate']['name'].split()[-1]

        #make sure if they have a first and last and what not
        if " " not in breezy_candidate['candidate']['name']:
            last_name = ""
        position = breezy_candidate['position']['name']
        location = breezy_candidate['position']['position']['location']['name']
        phone_number = ""
        email_address = ""
        for i in breezy_candidate['candidate']:
            if i == 'phone_number':
                phone_number = breezy_candidate['candidate']['phone_number']
            if i == 'email_address':
                email_address = breezy_candidate['candidate']['email_address']

        #if it was a candidate added, added them into ricochet, and put them in the texting pipeline
        if request.json['type'] == 'candidateAdded':

            acuity_link =  "https://encorsolar.as.me/?appointmentType=19039217&firstName="+first_name+"&lastName="+last_name+"&field:8821576="+candidate_id+"&phone="+phone_number+"&email="+email_address+'&field:8927450='+position+location
            
            #this block of text send the info to ricochet and adds a custom attribute that is the breezy id to search for later
            ricochet_lead_values = {
                'phone': phone_number,
                "firstName": first_name,
                'lastName':last_name,
                'acuity_link':acuity_link,
                'position':position,
                'location':location
                }
            
            ricochet_lead_id = requests.post('https://leads.ricochet.me/api/v1/lead/create/Breezy?token='+ricochet_post_token, data=ricochet_lead_values).json()["lead_id"]

            #this adds the custom url to the candidate
            header.addCustom(candidate_id,position_id,'Custom Link',acuity_link)

            #this code saves the candidate
            contacted_candidate = [[candidate_id,position_id,ricochet_lead_id]]
            header.add_file(contacted_candidate,'/home/ubuntu/uncontacted_candidates.csv')

            header.addReporting(breezy_candidate)
            
            header.updateStage(candidate_id,position_id,'Texting')
            
        #if it was a delete, delete them from acuity and the csv
        elif request.json['type'] == 'candidateDeleted':
            requests.delete("https://acuityscheduling.com/api/v1/clients?firstName="+first_name+"&lastName="+last_name+"&phone="+phone_number, auth=(acuity_user_id,acuity_api_key))
            header.delete_file(candidate_id, '/home/ubuntu/uncontacted_candidates.csv')

        return Response(status=200)
        
    #check for didferent errors and log them.
    except IndexError:
        logger.error("Someone managed to put something invalid")
        logger.exception("message")  
        return Response(status=400)
    except KeyError:
        logger.error("Someone managed to put something invalid")
        logger.exception("message")  
        return Response(status=400)
    except:
        logger.error("Unexpected error:")  
        logger.exception("message")  
        return Response(status=500)


#this is the function that triggers when anything is changed on a acuity appointment. While we don't need to know every change,
#it is important to be able know when a disposition is change. In an ideal world, the disposition is only changed once, maybe twice
#it should only do things when the disposition is changed and this should only happen at the end of an interview.
@app.route('/dispositionChanged', methods=['POST'])
def dispositionChanged():
    try:
        #take the appointment and get the breezy id out of it
        acuity = requests.get("https://acuityscheduling.com/api/v1/appointments/"+request.form['id'], auth=(acuity_user_id,acuity_api_key))

        for i in acuity.json()['forms']:
            if i['name'] == "Candidate Id":
                candidate_id = i['values'][0]['value']
            if i['name'] == "Interview Disposition":
                disposition = i['values'][0]['value']
        
        position_id = header.find_file(candidate_id, '/home/ubuntu/uncontacted_candidates.csv')[0][1]
        lead_id = header.find_file(candidate_id, '/home/ubuntu/uncontacted_candidates.csv')[0][2]

        #when the dispostion is changed have reporting reflect that
        update = {
            'intDisposition':disposition,
            'intConductedDate':datetime.now().date()
        }
        header.updateReporting(candidate_id,update)

        #if something was changed, get the new disposition and act accordingly by changeing stuff in breezy and whatnot
        if request.form['action'] == 'changed':
            #get the correct pipleine stage based off of the disposistion
            if disposition == "Offer Accepted": #Offer Accepted
                header.updateStage(candidate_id,position_id,'Onboarding')
                header.updateStatus(lead_id,header.hired_ric)
                update = {
                    'hiredDate':datetime.now().date()
                }
                header.updateReporting(candidate_id,update)
            elif disposition == "Offer Declined": #Offer Declined
                header.offbaord(candidate_id,"Offer Made - Not Accepted")
                
            elif disposition == "Disqualified": #Disqualified
                header.offbaord(candidate_id,"Not Offered")

            #this needs to know a few things, did they schedule from a text or were they called (I can check this by seeing if they were in a contacted status previousely), if they were 
            # called, put them into noshow(owned) otherwise if they noshow an interview, and were never in a contact status put them in the noshow status. second, have they no 
            # showed an interview before, if they have and are doing it again, we need to update their breezy to disqaulifed as well as ricochet.
            elif disposition == "No Show": #this is a problem because of rescheduling
                header.updateStatus(lead_id,header.interview_no)
                no_show = False
                rescheduled = False
                for i in header.get_candidate(candidate_id,position_id).json()['custom_attributes']:
                    if i['name'] == 'No Show':
                        no_show = True
                        if i['value'] != request.form['id']:
                            header.offbaord(candidate_id,"No Showed Twice")
                    if i['name'] == 'Has Rescheduled':
                        rescheduled = True
                if no_show and rescheduled: #if they have no showed before, and have reshceduled before
                    header.offbaord(candidate_id,"No Showed Twice")
                    
                if no_show != True:
                    header.addCustom(candidate_id,position_id,'No Show',request.form['id'])

            elif disposition == "Offer Pending":
                pass
            
            elif disposition == "Pending":
                pass

            return Response(status=200)
        else:
            return Response(status=201)

    #check for didferent errors and log them.
    except KeyError:
        logger.error("Someone is missing necassary information")
        logger.exception("message")  
        return Response(status=401)
    except UnboundLocalError:
        logger.error("Someone is missing necassary information")
        logger.exception("message")  
        return Response(status=401)
    except IndexError:
        logger.error("There is some issue finding a candidate in the csv")
        logger.exception("message")  
        contacted_candidate = [[candidate_id,position_id,lead_id]]
        header.add_file(contacted_candidate,'/home/ubuntu/uncontacted_candidates.csv')
        return Response(status=501)
    except:
        logger.error("Unexpected error:")  
        logger.exception("message")  
        return Response(status=500)
    

#this functino should trigger everytime a candidates dispostiion in ricochet changes. If we set this up the way I think we will
#this will tell me if theyve been contated and would like to be called back, or if they havnt been contacted
#This has now become, "everytime a status is changed, do something"
#I'm thinking that most of this automatino can be done in ricochet, but for reporting reason, it makes sense to have
#everything in here just in case
@app.route("/statusUpdated", methods=["POST"])
def statusUpdate():
    try:
        lead = request.json
        #get information from the request data
        lead_id = lead['id']
        candidate_id = header.find_file(lead_id,'/home/ubuntu/uncontacted_candidates.csv',2)[0][0]
        position_id = header.find_file(lead_id,'/home/ubuntu/uncontacted_candidates.csv',2)[0][1]

        header.addCustom(candidate_id,position_id,'Ricochet Status',lead['status'])

        #cange stuff in breezy and reporting based on what stage they were changed to
        if lead['status'] == "2. CONTACTED - Wrong Numebr" or lead['status'] == "2. CONTACTED - Not Interested": #if they are contacted and need to be dropped
            update = {
                'contactedOn':header.find_file(candidate_id,'/home/ubuntu/reporting.csv')[0][7]
            }
            header.updateReporting(candidate_id,update)
            header.offbaord(candidate_id, lead['status'])
        
        elif lead['status'] == '2. CONTACTED - Interview Scheduled' or lead['status'] == '2. CONTACTED - Callback/Task set':#if they have been conated but are still a lead
            update = {
                'contactedOn':header.find_file(candidate_id,'/home/ubuntu/reporting.csv')[0][7]
            }
            header.updateReporting(candidate_id,update)

        elif lead['status'] == "0. NEW - Dial": #this is when they are in theyve been texted twice
            header.updateStage(candidate_id,position_id,'Dialing')
        
        elif lead['status'] == "4. DISQUALIFIED":#when they hit an endpoint, delete them from the csv
            header.delete_file(candidate_id, '/home/ubuntu/uncontacted_candidates.csv')
        
        return Response(status=200)
    #check for didferent errors and log them.
    except KeyError:
        logger.error("Some necassary info is missing")
        logger.exception("message")  
        return Response(status=401)
    except IndexError:
        logger.error("There is some issue finding a candidate in the csv")
        logger.exception("message")  
        contacted_candidate = [[candidate_id,position_id,lead_id]]
        header.add_file(contacted_candidate,'/home/ubuntu/uncontacted_candidates.csv')
        return Response(status=501)
    except:
        logger.error("Unexpected error:")  
        logger.exception("message")  
        return Response(status=500)

#this just keeps track of how many times weve called a candidate.
#then it updates reporting with that info.
@app.route("/leadCalled", methods=["POST"])
def leadCalled():
    try:
        lead_id = request.json['lead']
        candidate_id = header.find_file(lead_id,'/home/ubuntu/uncontacted_candidates.csv',2)[0][0]

        update = {
            'timesCalled':int(header.find_file(candidate_id,'/home/ubuntu/reporting.csv')[0][7])+1
        }
        header.updateReporting(candidate_id,update)
        return Response(status=200)
    except:
        logger.error("Unexpected error:")  
        logger.exception("message")  
        return Response(status=500)

#this just runs the code on port 80, and will accept info form anyone (unofrtuantly this is necsassry
#to get the webhooks from the different sites.)
if __name__ == '__main__':
	app.run(port=80,host='0.0.0.0')

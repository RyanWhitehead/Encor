##Ryan Whitehead
##12/01/2020
##This script is what will run if the system is down for any amount of time
##the idea is that, id for whatever reason, the code stops running, this
##will go through the entire database and fix any "pending" actions
##it might be smart to run this on a local computer so that im not using
##a bunch of cpu credits and what not

##There are far better ways to do this, and plenty of ineffincencies in this script, but with any luck it should
##be temporary so as long as it works i do not care

## TODO
##     -Make sure to look at every single calendar when looking for appointments
##
##     -Make sure to include every position
##
##     -find a way to automatically pull the uncontacted candidates, and to replace it

from flask import Flask, request, Response, json
import head
import requests, boto3, json
from datetime import datetime

email = "r.whitehead@encorsolar.com"
password = "ilikemewaffles12"
breezy_company_id = "3446d8d33d15"
acuity_user_id = "21303593"
acuity_api_key = "17ebea1a38641310ebcc5e6fcef422b4"
position_id = "7e33893fc75b"
position_name = "test"

sign_in = {"email":email,'password':password}
breezy_auth = requests.post('https://api.breezy.hr/v3/signin',data=sign_in).json()['access_token']
breezy_header = {'Authorization':breezy_auth}

ricochet_headers = {'Content-Type':'application/json'}

ricochet_post_token = 'dd5da565905396e4860d92f70ddad37b'

#First we need to get every candidate and determine which ones are new by Checking to see if they
#are in the applied stage. then we need to send all of those candidates a text, and do all the other stuff we usually do
try:
    candidates = requests.get("https://api.breezy.hr/v3/company/"+breezy_company_id+"/position/"+position_id+"/candidates",headers=breezy_header).json()
    for i in candidates:
        if i['stage']['id'] == head.Applied:
            candidate_id = i['_id']
            breezy_candidate = head.get_candidate(candidate_id,position_id).json()

            first_name = breezy_candidate['name'].split()[0]
            last_name = breezy_candidate['name'].split()[-1]
            if " " not in breezy_candidate['name']:
                last_name = ""
            phone_number = ""
            email_address = ""
            for i in breezy_candidate:
                if i == 'phone_number':
                    phone_number = breezy_candidate[i]
                if i == 'email_address':
                    email_address = breezy_candidate[i]

            acuity_link =  "https://encorsolar.as.me/?appointmentType=18537783&firstName="+first_name+"&lastName="+last_name+"&field:8821576="+candidate_id+"&phone="+phone_number+"&email="+email_address
            
            #this block of text send the info to ricochet and adds a custom attribute that is the breezy id to search for later
            ricochet_lead_values = {
                'phone': phone_number,
                "firstName": first_name,
                'lastName':last_name,
                'acuity_link':acuity_link,
                'position':position_name,
                'status': "0. NEW"
                }
            
            ricochet_lead_id = requests.post('https://leads.ricochet.me/api/v1/lead/create/Breezy?token='+ricochet_post_token, data=ricochet_lead_values).json()["lead_id"]

            #this adds the custom url to the candidate
            head.addCustom(candidate_id,position_id,'Custom Link',acuity_link)

            #this code saves the candidate
            contacted_candidate = [[candidate_id,position_id,ricochet_lead_id]]
            head.add_file(contacted_candidate)
            
            head.updateStage(candidate_id,position_id,head.Texting)    
except IndexError:
    print("Someone managed to put something invalid")
except KeyError:
    print("Someone managed to put something invalid")
except:
    print("Unexpected error:")  

#then we need to pull every person in a stage where they could have sheduled an interview.
#(texting,dialing) and see if they have sheduled one by getting their candidate id, and checking to see if anyone in
#acuity has that same candidate id. Then do anything we would normally do (change them to interviewing)
try:
    interviews = requests.get("https://acuityscheduling.com/api/v1/appointments?calendarID=4766387", auth=(acuity_user_id,acuity_api_key)).json()
    for i in candidates:
        candidate_id = i["_id"]
        if i['stage']['id'] == head.Texting or i['stage']['id'] == head.Dialing or i['stage']['id'] == head.Interviewing:
            for j in interviews:
                for k in j['forms']:
                    if k['name'] == "Candidate Id":
                        acuity_candidate_id = k['values'][0]['value']
                        if acuity_candidate_id == candidate_id:
                            full_name = j['firstName']+" "+j['lastName']
                            phone = j['phone']
                            email = j['email']
                            lead_id = head.find_file(candidate_id)[0][2]

                            breezy_update_url = 'https://api.breezy.hr/v3/company/'+breezy_company_id+'/position/'+position_id+'/candidate/'+i['_id']

                            #update breezy stage
                            update_info = {
                                'name':full_name,
                                'phone_number':phone,
                                'email_adress':email
                            }
                            requests.put(breezy_update_url, data=update_info, headers=breezy_header)
                            head.updateStage(candidate_id,position_id,head.Interviewing)
                            head.addCustom(candidate_id,position_id,'appointment_id',j['id'])
                            #update ricochet status
                            head.updateStatus(lead_id,head.contacted_interview)
except UnboundLocalError:
    print("Someone is missing necassary information")

except KeyError:
    print("Someone is missing necassary information")

except IndexError:
    print("There is some issue finding a candidate in the csv")
    contacted_candidate = [[candidate_id,position_id,lead_id]]
    head.add_file(contacted_candidate)


#Then we need to see if any interviews were conducted while the system was down, and see what the disposition is
#the best way to do this is pull every candidate that was interviewing, and check to see if their interview has
#a disposition
try:
    for i in candidates:
        has_one = False
        if i['stage']['id'] == head.Interviewing:
            current = head.get_candidate(i['_id'],position_id).json()
            candidate_id = i['_id']
            for j in current['custom_attributes']:
                if j['name'] == 'appointment_id':
                    app_id = j['value']
            acuity = requests.get("https://acuityscheduling.com/api/v1/appointments/"+app_id, auth=(acuity_user_id,acuity_api_key))
            for j in acuity.json()['forms']:
                if j['name'] == "Interview Disposition":
                    disposition = j['values'][0]['value']
                    has_one = True
                    
            if has_one: #if they have a disposition
                if disposition == "Offer Made - Accepted": #Offer Accepted
                    head.updateStage(candidate_id,position_id,head.Onboarding)
                    head.updateStatus(lead_id,head.hired_ric)
                    
                elif disposition == "Offer Made - Not Accepted": #Offer Declined
                    head.offbaord(candidate_id,"Offer Made - Not Accepted")
                    
                elif disposition == "Not Offered": #Disqualified
                    head.offbaord(candidate_id,"Not Offered")

                #this needs to know a few things, did they schedule from a text or were they called (I can check this by seeing if they were in a contacted status previousely), if they were 
                # called, put them into noshow(owned) otherwise if they noshow an interview, and were never in a contact status put them in the noshow status. second, have they no 
                # showed an interview before, if they have and are doing it again, we need to update their breezy to disqaulifed as well as ricochet.
                elif disposition == "No Show": #this is a problem because of rescheduling
                    no_show = False
                    rescheduled = False
                    for i in head.get_candidate(candidate_id,position_id).json()['custom_attributes']:
                        if i['name'] == 'No Show':
                            no_show = True
                            if i['value'] != app_id:
                                head.offbaord(candidate_id,"No Showed Twice")
                        if i['name'] == 'Has Rescheduled':
                            rescheduled = True
                    if no_show and rescheduled: #if they have no showed before, and have reshceduled before
                        head.offbaord(candidate_id,"No Showed Twice")
                        
                    if no_show != True:
                        head.addCustom(candidate_id,position_id,'No Show',app_id)

                elif disposition == "Offer Pending" or disposition == "Pending":
                    pass
except IndexError:
    print("Someone managed to put something invalid")
except KeyError:
    print("Someone managed to put something invalid")
except:
    print("Unexpected error:")  

#I need to see if anybodys status has changed, if it has do the normal thing.
try:
    for i in candidates:
        current = head.get_candidate(i['_id'],position_id).json()
        past_status = ""
        for j in current['custom_attributes']:
                if j['name'] == 'Ricochet Status':
                    past_status = j['value']
        candidate_id = i['_id']
        lead_id = head.find_file(candidate_id)[0][2]
        heads = {
            "X-Auth-Token":'12ecb6b2de32aa386aaff01e1cd684',
            "Content-Type":"application/json"
            }
        lead = requests.get("https://ricochet.me/api/v4/leads/"+lead_id, headers=heads).json()['data']['lead']

        current_status = lead['currentstatus']['name']

        candidate_id = head.find_file(lead_id,2)[0][0]
        position_id = head.find_file(lead_id,2)[0][1]

        if past_status != current_status:

            head.addCustom(candidate_id,position_id,'Ricochet Status',current_status)

            if current_status == "2. CONTACTED - Not Interested": #this is when we learn they are no longer interested over the phone
                head.offbaord(candidate_id, current_status)
                head.updateStatus(lead_id,head.disqualified_ric)

            elif current_status == "2. CONTACTED - Wrong Numebr": #this is when they no show twice
                head.offbaord(candidate_id, current_status)
                head.updateStatus(lead_id,head.disqualified_ric)

            elif current_status == "0. NEW - Dial": #this is when they are in theyve been texted twice
                head.updateStage(candidate_id,position_id,head.Dialing)
            
            elif current_status == "4. DISQUALIFIED":#when they hit an endpoint, delete them from the csv
                head.delete_file(candidate_id)
except KeyError:
    print("Someone is missing necassary information")
except UnboundLocalError:
    print("Someone is missing necassary information")
except IndexError:
    print("There is some issue finding a candidate in the csv")
    contacted_candidate = [[candidate_id,position_id,lead_id]]
    head.add_file(contacted_candidate)
except:
    print("Unexpected error:")  
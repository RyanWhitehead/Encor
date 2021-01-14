import csv, requests, json, boto3, logging, os
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler

#The breezy dispositions
stages = {
    'applied':'applied',
    'Texting':1607027590363,
    'Dialing':1607027635579,
    'Interviewing':1607027671797,
    'Onboarding':1607027688837,
    'Hired':1607027716017,
    "Disqualified":1607027736983
}

#the ricochet Status
hired_ric = 18864
disqualified_ric = 19166
interview_no_owned = 19051
interview_no = 18861
contacted_wrong_number = 18858
contacted_not_interested = 18857
contacted_interview = 18860
contacted_call_back = 18859
called_no_contact = 18856
called_left_message = 18855
new_dial = 19050
new = 18823

#this takes what secret you want, and gets it from amazon
def get_secret(secret):

    secret_name = "Breezy_sign_in"
    region_name = "us-east-2"

    # Create a Secrets Manager client
    session = boto3.session.Session()
    client = session.client(service_name='secretsmanager',region_name=region_name)

    get_secret_value_response = client.get_secret_value(SecretId=secret_name)
    secret_json = get_secret_value_response['SecretString']
    return json.loads(secret_json)[secret]

#this gets the secrets from amazon
sign_in = {"email":get_secret('breezy_email'),'password':get_secret('breezy_password')}
breezy_auth = requests.post('https://api.breezy.hr/v3/signin',data=sign_in).json()['access_token']
breezy_header = {'Authorization':breezy_auth}
breezy_company_id = get_secret('breezy_company_id')

acuity_user_id = get_secret('acuity_user_id')
acuity_api_key = get_secret('acuity_api_key')

#this sets up the stuff for putting the reporintg csv into the ondrive
fileName = 'Reporting.csv'
data = {'grant_type':"client_credentials", 
        'resource':"https://graph.microsoft.com", 
        'client_id':get_secret('client_id'), 
        'client_secret':get_secret('client_secret')
        } 
URL = "https://login.windows.net/"+get_secret('domain')+"/oauth2/token"
r = requests.post(url = URL, data = data) 
j = json.loads(r.text)
TOKEN = j["access_token"]
URL = "https://graph.microsoft.com/v1.0/users/ethan.whitehead@encorbi.com/drive/root:/Encor Reports"
headers={'Authorization': "Bearer " + TOKEN}

#this is just a pretty way to print json
def jprint(obj):
	text = json.dumps(obj, sort_keys=True, indent=4)
	print(text)

#this writes to a csv
def write_file(row, where):
    add_file = open(where, 'w')

    with add_file:
        writer = csv.writer(add_file)
        writer.writerows(row)
    return

#this addes a row to a csv
def add_file(row, where):
    add_file = open(where, 'a')

    with add_file:
        writer = csv.writer(add_file)
        writer.writerows(row)
    return

#this deletes a given row from a csv
def delete_file(to_delete, file, look_up=0):

    found = False
    lines = []
    deleted = []
    delete_file = open(file, 'r')    
    with delete_file:

        reader = csv.reader(delete_file)

        for row in reader:
            lines.append(row)
            if row == []:
                lines.remove(row)
            found = False
            for field in row:
                if field == to_delete and row[look_up] == field and found != 1:
                    lines.remove(row)
                    deleted.append(row)
                    found = True
     
    write_file(lines, file) 
    return deleted

#this finds a file in a csv
def find_file(to_find, file, look_up=0):
    found = False
    found_rows = []
    find_file = open(file, 'r')    
    with find_file:

        reader = csv.reader(find_file)

        for row in reader:
            found = False
            for field in row:
                if field == to_find and row[look_up] == field and found != 1:
                    found_rows.append(row)
                    found = True

        return found_rows

#this gets the candidate from breezy
def get_candidate(candidate_id,position_id):
    breezy_candidate_url = 'https://api.breezy.hr/v3/company/'+breezy_company_id+'/position/'+position_id+'/candidate/'+candidate_id

    breezy_candidate = requests.get(breezy_candidate_url, headers=breezy_header)
    return breezy_candidate

#this adds a custom attribute to a breezy candidate
def addCustom(candidate_id, position_id, name, value):
    breezy_custom_params = {"name":name, 'value':value}
    breezy_custom_url = 'https://api.breezy.hr/v3/company/'+breezy_company_id+'/position/'+position_id+'/candidate/'+candidate_id+'/custom-attribute'

    requests.put(breezy_custom_url, data=breezy_custom_params, headers=breezy_header)

#this updates the status in ricochet of a given lead to a given status
def updateStatus(lead_id, new_status):
    print(lead_id,new_status)
    head = {
        "X-Auth-Token":get_secret('ricochet_user_token'),
        "Content-Type":"application/json"
        }
    body = json.dumps({
        "status_id": new_status
        })
    r = requests.post("https://ricochet.me/api/v4/leads/"+lead_id+"/status", data=body, headers=head)
    print(r)
    jprint(r.json())

#this does some things to get rid of the info of the candidate.
def offbaord(candidate_id, reason):
    #get the person who wasnt contacted
    position_id = find_file(candidate_id,'/home/ubuntu/uncontacted_candidates.csv')[0][1]
    lead_id = find_file(candidate_id,'/home/ubuntu/uncontacted_candidates.csv')[0][2]
    #update their stage to whatever, and delete them from the csv
    addCustom(candidate_id,position_id,'Discard Reason',reason)
    updateStage(candidate_id,position_id,'Disqualified')
    updateStatus(lead_id, disqualified_ric)

#this adds a file to the reporintg csv when we get a new candidate
def addReporting(candidate):#this will be the function that runs when there is a new candidate added
    first_name = candidate['candidate']['name'].split()[0]
    last_name = candidate['candidate']['name'].split()[-1]
    location = candidate['position']['position']['location']['name']
    position = candidate['position']['name']
    if " " not in candidate['candidate']['name']:
        last_name = "lastName"

    phone_number = "phone"
    email_address = "email"
    for i in candidate['candidate']:
        if i == 'phone_number':
            phone_number = candidate['candidate']['phone_number']
        if i == 'email_address':
            email_address = candidate['candidate']['email_address']

    candidate = [[candidate['candidate']['_id'],'', first_name, last_name, location, position, phone_number, email_address, datetime.now().date(), '0', '', datetime.now().date(), datetime.now().date() + timedelta(days=1),'', '','',"","",'', '']]
    add_file(candidate, '/home/ubuntu/reporting.csv')
    #then send the file to onedrive
    file = open('/home/ubuntu/reporting.csv', 'rb').read()
    r = requests.put(URL+"/"+fileName+":/content", data=file, headers=headers)
    return r

#this will take an id for lookup, and a dictionary with keys that represent the columns that we would like to change, the values will be the new values.
def updateReporting(candidate_id, to_update): #this is the function that runs whenever anything is changed
    old = find_file(candidate_id,'/home/ubuntu/reporting.csv')[0]
    delete_file(candidate_id, '/home/ubuntu/reporting.csv')
    columns = ["id", 'recruiter', "firstName", "lastName", 'location', 'position', 'phone', 'email', 'appliedOn', 'timesCalled', 'contactedOn', 'textDate1','textDate2', 'intScheduledOn', 'intScheduledFor',"hiredDate","startedDate",'intDisposition','breezyStatus']
    new_full = [[]]
    new = new_full[0]
    for i in range(len(columns)):
        try:
            if to_update[columns[i]] != old[i]:
                new.append(to_update[columns[i]])
            else:
                new.append(old[i])
        except KeyError:
            new.append(old[i])
    add_file(new_full, '/home/ubuntu/reporting.csv')
    file = open('/home/ubuntu/reporting.csv', 'rb').read()
    r = requests.put(URL+"/"+fileName+":/content", data=file, headers=headers)
    return r

#this updates the stage of the breezy candidate.
def updateStage(candidate_id,position_id,stage):
    breezy_stage = {'stage_id':stages[stage]}
    breezy_custom_url = 'https://api.breezy.hr/v3/company/'+breezy_company_id+'/position/'+position_id+'/candidate/'+candidate_id+'/stage'

    requests.put(breezy_custom_url, data=breezy_stage, headers=breezy_header)
    update = {
        'breezyStatus':stage
    }
    #updateReporting(candidate_id,update)

import csv, requests, json, csv, boto3
from datetime import datetime

#testing again

#The breezy dispositions
Applied      = 'applied'
Texting      = 1606848913927
Disqualified = 'disqualified'
Dialing      = 1606848954990
Interviewing = 1606849078784
Onboarding   = 1606849114297
Hired        = 1606849160320

#the ricochet Status
disqualified_ric = 11111
new = 18823
new_dial = 19050
called_left_message = 18855
called_no_contact = 18856
contacted_call_back = 18859
contacted_not_interested = 18857
contacted_wrong_number = 18858
interview_completed = 18863
interview_dropped = 18862
interview_no_show = 18861
interview_scheduled = 18860
hired_ric = 18864

def get_secret(secret):

    secret_name = "Breezy_sign_in"
    region_name = "us-east-2"

    # Create a Secrets Manager client
    session = boto3.session.Session()
    client = session.client(service_name='secretsmanager',region_name=region_name)

    get_secret_value_response = client.get_secret_value(SecretId=secret_name)
    secret_json = get_secret_value_response['SecretString']
    return json.loads(secret_json)[secret]

sign_in = {"email":get_secret('breezy_email'),'password':get_secret('breezy_password')}
breezy_auth = requests.post('https://api.breezy.hr/v3/signin',data=sign_in).json()['access_token']
breezy_header = {'Authorization':breezy_auth}
breezy_company_id = get_secret('breezy_company_id')

acuity_user_id = get_secret('acuity_user_id')
acuity_api_key = get_secret('acuity_api_key')



def jprint(obj):
	text = json.dumps(obj, sort_keys=True, indent=4)
	print(text)

#wirte
def write_file(file):
    write_file = open('uncontacted_candidates.csv', 'w')

    with write_file:
        writer = csv.writer(write_file)
        writer.writerows(file)

    return

#add
def add_file(row):
    add_file = open('uncontacted_candidates.csv', 'a')

    with add_file:
        writer = csv.writer(add_file)
        writer.writerows(row)
    return

#delete
def delete_file(to_delete, look_up=0):

    found = False
    lines = []
    deleted = []
    delete_file = open('uncontacted_candidates.csv', 'r')    
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
     
    write_file(lines) 
    return deleted

def find_file(to_find, look_up=0):
    found = False
    found_rows = []
    find_file = open('uncontacted_candidates.csv', 'r')    
    with find_file:

        reader = csv.reader(find_file)

        for row in reader:
            found = False
            for field in row:
                if field == to_find and row[look_up] == field and found != 1:
                    found_rows.append(row)
                    found = True

        return found_rows
    
def update_appointment(to_find, new_value,key=3):
    change = find_file(to_find)
    delete_file(to_find)
    change[0][key] = new_value
    add_file(change)

def get_candidate(candidate_id,position_id):
    breezy_candidate_url = 'https://api.breezy.hr/v3/company/'+breezy_company_id+'/position/'+position_id+'/candidate/'+candidate_id

    breezy_candidate = requests.get(breezy_candidate_url, headers=breezy_header)
    return breezy_candidate


def updateStage(candidate_id,position_id,stage):
    breezy_stage = {'stage_id':stage}
    breezy_custom_url = 'https://api.breezy.hr/v3/company/'+breezy_company_id+'/position/'+position_id+'/candidate/'+candidate_id+'/stage'

    requests.put(breezy_custom_url, data=breezy_stage, headers=breezy_header)
    
def addCustom(candidate_id, position_id, name, value):
    breezy_custom_params = {"name":name, 'value':value}
    breezy_custom_url = 'https://api.breezy.hr/v3/company/'+breezy_company_id+'/position/'+position_id+'/candidate/'+candidate_id+'/custom-attribute'

    requests.put(breezy_custom_url, data=breezy_custom_params, headers=breezy_header)


def updateStatus(lead_id, new_status):
    print("this is happeneing",lead_id,new_status)
    head = {
        "X-Auth-Token":"12ecb6b2de32aa386aaff01e1cd684",
        "Content-Type":"application/json"
        }
    body = {
        "status_id": new_status
        }
    r = requests.post("https://ricochet.me/api/v4/leads/"+lead_id+"/status", data=body, headers=head)
    print(r)
    jprint(r.json())
    print(new_status)

def unasign(lead):
    #get the person who wasnt contacted
    candidate_id = lead['candidate_id']
    position_id = find_file(candidate_id)[0][1]
    #update their stage to whatever, and delete them from the csv
    addCustom(candidate_id,position_id,'Discard Reason',lead['status'])
    updateStage(candidate_id,position_id,Disqualified)
    #drop them from the csv
    delete_file(candidate_id)
    

#!/usr/bin/env python
import sys  
import json
import argparse
import requests
import msal
import os 
import time
from os.path import expanduser
from ConfigParser import SafeConfigParser
from os import environ
import base64
configParser = SafeConfigParser()

sys.path.insert(0,'/opt/mitsogo')

secret = ''
client_id = ''

try:
    configParser.read(os.environ.get('SHARED_CREDENTIALS_FILE',os.path.join(expanduser("~"),'.mitsogo/credentials')))
    secret = configParser.get('onedrive','value')
    client_id = configParser.get('onedrive','client_id')
except:
    pass

try:
    from production import *
except:
    pass

if environ.get('ONEDRIVE_CLIENTID',None) and environ.get('ONEDRIVE_VALUE',None):
    secret = os.environ('ONEDRIVE_VALUE')
    client_id = os.environ('ONEDRIVE_CLIENTID')

if not secret and not client_id:
    print "secret or client_id missing"
    sys.exit(1)

tenent = "mitsogo.com"
authority = "https://login.microsoftonline.com/" + tenent
scope = "https://graph.microsoft.com/.default"
app = msal.ConfidentialClientApplication(client_id, authority=authority,client_credential=secret)
result = None
result = app.acquire_token_for_client(scopes=scope)
header = {'Authorization': 'Bearer ' + result['access_token']}

def upload(endpoint,file):
    file_data = open(path, 'rb')
    response=requests.put(endpoint+drive+"/"+file+":/content",headers=header, data=file_data).json()    
    return response
   
def session_upload(endpoint,file):
    upload_session=requests.post(endpoint+drive+"/"+file+":/createUploadSession", headers=header).json()
    with open(path, 'rb') as f:
        total_file_size = os.path.getsize(path)
        chunk_size = 327680
        chunk_number = total_file_size//chunk_size
        chunk_leftover = total_file_size - chunk_size * chunk_number
        i = 0
        while i <= chunk_number:
            chunk_data = f.read(chunk_size)
            start_index = i*chunk_size
            end_index = start_index + chunk_size
            if i == chunk_number:
                end_index = start_index + chunk_leftover
            headers = {'Content-Length':'{}'.format(chunk_size),'Content-Range':'bytes {}-{}/{}'.format(start_index, end_index-1, total_file_size)}
            time.sleep(2)
            response = requests.put(upload_session['uploadUrl'], data=chunk_data, headers=headers).json()
            i += 1
        return response



def permission(value):
    r = requests.post(endpoint+drive+"/"+file+":/invite", headers=header,json={"requireSignIn": True,"sendInvitation": False,"roles": [types],"recipients": [{ "email":value }],"message": "string"})
    if r.status_code == 200:
        print "permision added for  "+value
    else:
        print "adding permission failed for  "+value		

def link():
    if  link_gen == "true":
        re = requests.post(endpoint+drive+"/"+file+":/createLink", headers=header,json={"type": "view", "scope": "users"}).json()
        print re['link']['webUrl']
    if list:
        for value in list:
            permission(value)

def mail_permission(test,url=None):
    status = False
    if not url:
        url = "https://graph.microsoft.com/v1.0/groups/"
    group_response = requests.get(url, headers=header).json()
    for entry in group_response['value']:
        if entry['displayName'] == test:
            status = True
            id = entry['id']
            url = "https://graph.microsoft.com/v1.0/groups/"+id+"/members"
            member_response = requests.get(url, headers=header)

            if member_response.status_code == 200:
                response = member_response.json()
                for entry in response['value']:
                    mail_id = str(entry['mail'])
                    permission(mail_id)
    if not status and group_response.get('@odata.nextLink'):
        url  = group_response['@odata.nextLink']
        mail_permission(test,url)

def file_download():
    base64Value = base64.b64encode(str(args.download_url));
    encodedUrl = "u!" + base64Value[:-1].replace('/','_').replace('+','-')
    try:
        re=requests.get("https://graph.microsoft.com/v1.0/shares/"+encodedUrl+"/driveItem/content", headers=header,allow_redirects=True)
    except Exception as ConnectionError:
        time.sleep(10)
        re=requests.get("https://graph.microsoft.com/v1.0/shares/"+encodedUrl+"/driveItem/content", headers=header,allow_redirects=True) 
    except Exception as e:
        print "file download failed"
       
    if re.status_code == 200:
        try:
            open(args.downloaded_file+".zip", 'wb').write(re.content)
            sys.exit(0)
        except Exception as e:
            raise e
            sys.exit(1)
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-path','--path',type=str,help='path to the file location')
    parser.add_argument('-user','--username',type=str,help='onedrive user name to which the files has to be uploaded ex:devops@mitsogo.com')
    parser.add_argument('-group','--group_name',help="group name  to which file  to be added")
    parser.add_argument('-d_path','--drive_path',default='',help="path to onedrive folder to which file has to be be uploaded default:root")
    parser.add_argument('-link','--link',default="true",help="add argument as false skip  link genertion default:true")
    parser.add_argument('-mail','--m_id',help='mail ids to which permmision to be added seperated by comma')
    parser.add_argument('-type','--type',default="read",type=str,help='type of permission to be added(write or read)')
    parser.add_argument('-p_group','--p_gp',type=str,help='name of the group to which the permission to be added example "Internal Devops,Android Team"')
    parser.add_argument('-url','--download_url',default=None,type=str,help='url to download file')
    parser.add_argument('-file','--downloaded_file',default=None,type=str,help='file name for the downloaded file')
    args = parser.parse_args()
    
    path = args.path
    user = args.username
    drive = args.drive_path
    link_gen = args.link
    group=args.group_name
    id = args.m_id
    types = args.type
    pgroup = args.p_gp
    flag = -1
    list = []
    if args.download_url:
       file_download()

    if group:
        url = "https://graph.microsoft.com/v1.0/groups"
        response = requests.get(url,headers=header).json()
        for values in response['value']:
            if values['displayName'] == group:
                group_id = values['id']
                flag = 1
        if flag  == -1 :
        	print  "{} do not exist".format(group)
        endpoint = "https://graph.microsoft.com/v1.0/groups/"+group_id+"/drive/root:/"
    elif user:
        endpoint = "https://graph.microsoft.com/v1.0/users/"+user+"/drive/root:/"
    else:
        print "no user name or group name specified \nexited"
        sys.exit(1)
    file = os.path.basename(path)
    file_size = os.stat(path).st_size
    if file_size < 4100000:
        result = upload(endpoint,file)
    else:
        result = session_upload(endpoint,file)
    if id:
        list = id.split(",")
    if result['webUrl']:
        print "upload succes"
        link()
    else:
        print "upload failed"
    if pgroup:
        group_name = pgroup.split(",")
        for value in group_name:
            mail_permission(value)

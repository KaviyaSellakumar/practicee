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
import logging

configParser = SafeConfigParser()
DEFAULT_CREDENTIALS_FILE = os.path.join(expanduser("~"),'.mitsogo/credentials')
logger = logging.getLogger(__name__)
FORMAT = "%(asctime)s {} {} - %(levelname)s - %(message)s".format(os.uname()[1],os.environ.get('technician','SYSTEM'))
logging.basicConfig(format=FORMAT, level=os.environ.get('LOGLEVEL','INFO'))

client_id = None
value = None

try:
    from production import client_id, value
except Exception as e:
    logger.info(e)

def getconfig(profile, variable, environment, default=""):
    try:
        configParser.read(os.environ.get('SHARED_CREDENTIALS_FILE', DEFAULT_CREDENTIALS_FILE))
        value = configParser.get(profile, variable)
    except:
        value = os.environ.get(environment, default)
    return value

def create_token(client_id, value):
    if not client_id and not value:
        client_id = getconfig('onedrive','client_id','ONEDRIVE_CLIENTID')
        value = getconfig('onedrive','value','ONEDRIVE_VALUE')
    tenent = "mitsogo.com"
    authority = "https://login.microsoftonline.com/" + tenent
    scope = ["https://graph.microsoft.com/.default"]
    app = msal.ConfidentialClientApplication(client_id, authority=authority, client_credential=value)
    result = app.acquire_token_for_client(scopes=scope)
    if result['access_token']:
        header = {'Authorization': 'Bearer ' + result['access_token'], "Content-Type": "application/json"}
        return header
    else:
        logger.error("Token generation failed")
        sys.exit(1)

def upload(endpoint, file_path, drive):
    with open(file_path, 'rb') as file_data:
        response = requests.put(endpoint + drive + "/" + file_path + ":/content", headers=header, data=file_data).json()    
    logger.debug(response)
    return response

def session_upload(endpoint, file_path, drive):
    upload_session = requests.post(endpoint + drive + "/" + file_path + ":/createUploadSession", headers=header).json()
    with open(file_path, 'rb') as f:
        total_file_size = os.path.getsize(file_path)
        chunk_size = 327680
        chunk_number = total_file_size // chunk_size
        chunk_leftover = total_file_size - chunk_size * chunk_number
        i = 0
        while i <= chunk_number:
            chunk_data = f.read(chunk_size)
            start_index = i * chunk_size
            end_index = start_index + chunk_size
            if i == chunk_number:
                end_index = start_index + chunk_leftover
            headers_chunk = {
                'Content-Length': '{}'.format(chunk_size),
                'Content-Range': 'bytes {}-{}/{}'.format(start_index, end_index-1, total_file_size)
            }
            time.sleep(2)
            response = requests.put(upload_session['uploadUrl'], data=chunk_data, headers=headers_chunk).json()
            i += 1
        logger.debug(response)
        return response

def create_sharing_link(drive, item, emails, groups, file_type):
    try:
        email_list = []
        if groups:
            modified_names = ["displayName eq '" + name + "'" for name in groups.split(',')]
            url = "https://graph.microsoft.com/v1.0/groups?$filter={}&$select=id".format(" or ".join(modified_names))
            groups_response = [k['id'] for k in requests.get(url, headers=header).json()['value']]
            for group_id in groups_response:
                mem_response = requests.get("https://graph.microsoft.com/v1.0/groups/" + group_id + "/members?$select=mail", headers=header).json()
                for member in mem_response['value']:
                    if member['mail'] and member['mail'] not in email_list:
                        email_list.append(str(member['mail']))
        if emails:
            email_list += emails.split(',')
        recipients = [{"email": e} for e in email_list] if email_list else None

        url = "{}/drives/{}/items/{}?$select=sharepointIds".format(base_url, drive, item)
        response = requests.get(url, headers=header).json()
        item_url = "https://graph.microsoft.com/beta/sites/{}/lists/{}/items/{}/createLink".format(site_id, library_id, response['sharepointIds']['listItemId'])
        data = {
            "type": file_type,
            "scope": "users",
            "recipients": recipients,
            "retainInheritedPermissions": True
        }
        link_response = requests.post(item_url, headers=header, json=data).json()
        if link_response['link']['webUrl']:
            return link_response['link']['webUrl']
        else:
            logger.error(link_response.get('error', {}).get('message', 'Unknown error'))
            return False
    except Exception:
        return False

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('file_path', type=str, help='provide file path')
    parser.add_argument('--site', default="Devops Hub", type=str, help='enter the site name')
    parser.add_argument('--library', default="Documents", type=str, help='Name of the document library')
    parser.add_argument('--p_type', default='blocksDownload', type=str, choices=['blocksDownload','view','edit'], help='type of permission for sharing link')
    parser.add_argument('--drive_path', default='', type=str, help='provide drive path of sharepoint default root')
    parser.add_argument('--link', default=True, help='generate sharing link')
    parser.add_argument('--mail', type=str, default=None, help='list of email ids separated by comma')
    parser.add_argument('--group', type=str, default=None, help='list of group names separated by comma')
    args = parser.parse_args()

    header = create_token(client_id, value)
    base_url = "https://graph.microsoft.com/v1.0"

    try:
        site_url = "{}/sites?search={}&select=id".format(base_url, args.site)
        site_response = requests.get(site_url, headers=header).json()['value']
        if not site_response:
            logger.error("{} site does not exist".format(args.site))
            sys.exit(1)
        site_id = site_response[0]['id']
        
        list_url = "{}/sites/{}/lists?$filter=displayName eq '{}'&select=id".format(base_url, site_id, args.library)
        response = requests.get(list_url, headers=header).json()['value']
        if not response:
            logger.error("{} library does not exist".format(args.library))
            sys.exit(2)
        library_id = response[0]['id']

        endpoint = "{}/sites/{}/lists/{}/drive/root:/".format(base_url, site_id, library_id)
        file_path = os.path.basename(args.file_path)
        file_size = os.stat(file_path).st_size
        if file_size < 4100000:
            result = upload(endpoint, file_path, args.drive_path)
        else:
            result = session_upload(endpoint, file_path, args.drive_path)

        if result.get('webUrl'):
            logger.info("Upload successful")
            if args.link:
                sharing_link = create_sharing_link(result['parentReference']['driveId'], result['id'], args.mail, args.group, args.p_type)
                if sharing_link:
                    logger.info("Successfully generated sharing link")
                    print("sharing link:{}".format(sharing_link))
                else:
                    logger.error("Link generation failed")
                    sys.exit(2)
    except Exception as e:
        raise e

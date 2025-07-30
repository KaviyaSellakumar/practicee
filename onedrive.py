#!/usr/bin/env python  
import sys    
import argparse  
import requests  
import msal  
import os   
import time  
import base64  
from os.path import expanduser  
from ConfigParser import SafeConfigParser  
from os import environ  

configParser = SafeConfigParser()

secret = ''  
client_id = ''  

try:  
    configParser.read(os.environ.get('SHARED_CREDENTIALS_FILE', os.path.join(expanduser("~"), '.mitsogo/credentials')))  
    secret = configParser.get('onedrive', 'value')  
    client_id = configParser.get('onedrive', 'client_id')  
except:  
    pass  

try:  
    from production import *  
except:  
    pass  

if environ.get('ONEDRIVE_CLIENTID', None) and environ.get('ONEDRIVE_VALUE', None):  
    secret = os.environ('ONEDRIVE_VALUE')  
    client_id = os.environ('ONEDRIVE_CLIENTID')  

if not secret and not client_id:  
    print "secret or client_id missing"  
    sys.exit(1)  

tenant = "mitsogo.com"  
authority = "https://login.microsoftonline.com/" + tenant  
scope = "https://graph.microsoft.com/.default"  
app = msal.ConfidentialClientApplication(client_id, authority=authority, client_credential=secret)  
result = app.acquire_token_for_client(scopes=scope)  
header = {'Authorization': 'Bearer ' + result['access_token']}  

def file_download():  
    base64Value = base64.b64encode(str(args.download_url))  
    encodedUrl = "u!" + base64Value[:-1].replace('/', '_').replace('+', '-')  
    try:  
        re = requests.get("https://graph.microsoft.com/v1.0/shares/" + encodedUrl + "/driveItem/content", headers=header, allow_redirects=True)  
    except Exception as ConnectionError:  
        time.sleep(10)  
        re = requests.get("https://graph.microsoft.com/v1.0/shares/" + encodedUrl + "/driveItem/content", headers=header, allow_redirects=True)  
    except Exception as e:  
        print "file download failed"  
        return  

    if re.status_code == 200:  
        try:  
            with open(args.downloaded_file + ".zip", 'wb') as f:  
                f.write(re.content)  
            print "Download successful"  
            sys.exit(0)  
        except Exception as e:  
            print "Failed to write file:", str(e)  
            sys.exit(1)  
    else:  
        print "Download failed. HTTP status:", re.status_code  
        sys.exit(1)  

if __name__ == '__main__':  
    parser = argparse.ArgumentParser()  
    parser.add_argument('-url', '--download_url', required=True, type=str, help='URL to download file')  
    parser.add_argument('-file', '--downloaded_file', required=True, type=str, help='Filename for the downloaded file')  
    args = parser.parse_args()  

    file_download()

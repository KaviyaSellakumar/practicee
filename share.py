#!/usr/bin/env python
import os
import sys
import json
import time
import logging
import argparse
import requests

from datetime import datetime, timedelta
from os.path import expanduser
import ConfigParser as configparser 

logger = logging.getLogger(__name__)
FORMAT = "%(asctime)s {} {} - %(levelname)s - %(message)s".format(
    os.uname()[1], os.environ.get('technician', 'SYSTEM')
)
logging.basicConfig(format=FORMAT, level=os.environ.get('LOGLEVEL', 'INFO'))
DEFAULT_CREDENTIALS_FILE = os.path.join(expanduser("~"), '.mitsogo/credentials')
configParser = configparser.ConfigParser()

def getconfig(profile, variable, environment, default=""):
    try:
        configParser.read(os.environ.get('SHARED_CREDENTIALS_FILE', DEFAULT_CREDENTIALS_FILE))
        value = configParser.get(profile, variable)
    except Exception:
        value = os.environ.get(environment, default)
    return value

def list_recent_repos(gitlab_server, token):
    headers = {'Private-Token': token}
    three_days_ago = datetime.utcnow() - timedelta(days=7)
    updated_after_iso = three_days_ago.strftime('%Y-%m-%dT%H:%M:%SZ')

    url = "{}/api/v4/projects?updated_after={}&per_page=100&order_by=updated_at&sort=desc".format(
    gitlab_server, updated_after_iso)

    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            projects = response.json()
            if projects:
                for project in projects:
                    logger.info("Repo: {} | Last Activity At: {} | URL: {}".format(
                        project['name'], project['last_activity_at'], project['web_url']
                    ))
            else:
                logger.info("No repositories updated in the last 3 days.")
        else:
            logger.error("Failed to fetch projects: {} - {}".format(
                response.status_code, response.text
            ))
    except Exception as e:
        logger.error("Exception while fetching updated repositories: {}".format(str(e)))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="List GitLab repositories updated in the last 3 days.")
    parser.add_argument('server', type=str, help="GitLab server ")
    args = parser.parse_args()

    gitlab_server = 'http://' + args.server
    
    if not token:
        logger.error("Token not found. Exiting.")
        sys.exit(1)

    list_recent_repos(gitlab_server, token)






#!/usr/bin/env python
import requests
from datetime import datetime
import argparse
from configparser import ConfigParser
import os
import logging
import csv
import sys
import json
try:
    from urllib.parse import urlencode
    from urllib.request import urlopen
except ImportError:
    from urllib import urlencode
    from urllib import urlopen


DEFAULT_CREDENTIALS_FILE = os.path.expanduser('~/.mitsogo/credentials')

logger = logging.getLogger(__name__)
FORMAT = "%(asctime)s {} {} - %(levelname)s - %(message)s".format(os.uname()[1],os.environ.get('technician','SYSTEM'))
logging.basicConfig(format=FORMAT, level=os.environ.get('LOGLEVEL','INFO'))

configParser = ConfigParser()
def getconfig(profile,variable,environment,default=""):
    try:
        configParser.read(os.environ.get('SHARED_CREDENTIALS_FILE', DEFAULT_CREDENTIALS_FILE))
        value = configParser.get(profile, variable)
    except Exception as e:
        logger.error("Unable to read credentials {}".format(e))
    return value
def gettoken(tenant_id, client_id, client_secret):
    try:
        token_url = "https://login.microsoftonline.com/{}/oauth2/v2.0/token".format(tenant_id)
        token_data = urlencode({
            'grant_type': 'client_credentials',
            'client_id': client_id,
            'client_secret': client_secret,
            'scope': 'https://graph.microsoft.com/.default'
        }).encode('utf-8')  # Encode to bytes for Python 3
        token_response = urlopen(token_url, token_data).read().decode('utf-8')
        token_response = json.loads(token_response)
        return token_response.get('access_token')
    except Exception as e:
        logger.error("gettoken- {}".format(e))
        sys.exit(1)

def get_certificate_details(access_token, threshold_days, ignorefile=None):
    try:
        outputlist = []
        graph_url = 'https://graph.microsoft.com/v1.0/applications'
        headers = {
            'Authorization': 'Bearer ' + access_token,
            'Accept': 'application/json'
        }
        
        # Handle pagination for applications
        next_link = graph_url
        while next_link:
            try:
                response = requests.get(next_link, headers=headers)
                response.raise_for_status()  # Raise exception for HTTP errors
                applications_data = response.json()
                
                # Process each application in the current page
                for application in applications_data.get('value', []):
                    app_name = application.get('displayName')
                    app_id = application.get('id')
                    app_appId = application.get('appId')
                    
                    # Get password credentials with pagination
                    certificates_url = "https://graph.microsoft.com/v1.0/applications/{}/passwordCredentials".format(app_id)
                    certificates_next_link = certificates_url
                    
                    while certificates_next_link:
                        cert_response = requests.get(certificates_next_link, headers=headers)
                        cert_response.raise_for_status()
                        certificates_data = cert_response.json()
                        
                        for certificate in certificates_data.get('value', []):
                            expiry_date_str = certificate.get('endDateTime', '').split('.')[0]
                            expiry_date_str = expiry_date_str.replace('Z', '')
                            
                            # Handle datetime in a way compatible with both Python versions
                            try:
                                expiry_date = datetime.strptime(expiry_date_str, '%Y-%m-%dT%H:%M:%S')
                                current_date = datetime.now()
                                days_until_expiry = (expiry_date - current_date).days
                                
                                if days_until_expiry <= threshold_days and days_until_expiry > 0:
                                    portal_url = "https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationMenuBlade/~/Overview/appId/{}".format(app_appId)
                                    outputlist.append([
                                        app_name,
                                        portal_url,
                                        certificate.get('displayName', ''),
                                        expiry_date,
                                        days_until_expiry
                                    ])
                            except (ValueError, AttributeError) as e:
                                logger.warning("Invalid date format for certificate in app '%s': %s", app_name, e)
                        
                        # Get the next page link for certificates if it exists
                        certificates_next_link = certificates_data.get('@odata.nextLink', None)
                
                # Get the next page link for applications if it exists
                next_link = applications_data.get('@odata.nextLink', None)
                
            except requests.exceptions.RequestException as e:
                logger.error("API request error: %s", e)
                break
                
        return outputlist
        
    except Exception as e:
        logger.error("Error in getting certificates: %s", e)
        sys.exit(1)

def generate_report(outputlist):
    status = 1
    try:
        with open(args.outputfile, 'w') as csvfile:
            csv_writer = csv.writer(csvfile)
            csv_writer.writerows(outputlist)
        logger.info("Report file {} generated successfully".format(args.outputfile))
        status = 0
    except Exception as e:
        logger.error(e)
        logger.error("Unable to generate file")
    return status

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Generate notification for expiring certificate")
    parser.add_argument("--threshold", default=7, type=int, help="Threshold days for checking expiry default 7")
    parser.add_argument("--outputfile", default="expiring_certificates.csv", help="Path of output csv file")
    parser.add_argument("--ignorefile", default="ignorelist.csv", help="Path of ignore csv file")
    args = parser.parse_args()

    tenant_id = getconfig("azure", "tenant_id", 'AZURE_TENANT_ID')
    client_id = getconfig("azure", "client_id", 'AZURE_CLIENT_ID')
    client_secret = getconfig("azure", "value", 'AZURE_CLIENT_SECRET')


    # Get access token using client credentials
    access_token = gettoken(tenant_id, client_id, client_secret)
    outputlist = get_certificate_details(access_token, args.threshold, args.ignorefile)

    if outputlist:
        outputlist = [['Application Name', 'url', 'Certificate Name', 'Expiry Date', 'Days Until Expiry']] + outputlist
        status = generate_report(outputlist)
    else:
        logger.info("No expiring certificate found")
        status = 0  
    sys.exit(status)







#!/bin/sh

projectdir=$(readlink -f `dirname "$0"`)

PATH=$PATH:/home/mitsadmin/.local/bin

message() {
    echo "$(date +'%Y-%m-%d %H:%M:%S') $HOSTNAME:$1"
}

message "info:changing working directory"
cd "$projectdir"

if [ ! -d reports ];then
    message "info:creating reports directory"
    mkdir -p reports
fi

message "info:generating reports for expiring secrets in Azure AD Apps"
ad_report="./AD_secrets_expiring_report_$(date +'%Y%m%d').csv"

python ./secrets_expiry_check.py --outputfile "$ad_report"
exitcode=$?
if [ $exitcode -eq 0 ];then
    message "info:successfully executed secrets_expiry_check.py script"
else
    message "critical:failed to generate report for expiring secrets in Azure AD Apps with exit code $exitcode"
    exit 1
fi

if [ -f $ad_report ];then
    message "info:mailing report for expiring secrets"
    var=`sharepointupload ${ad_report} --site "Devops Drive" \
            --drive_path /Devops_Scheduled_Reports/AD_secrets_expiring_report/`
    exitcode=$?
    link=`echo $var|grep "sharing link"|cut -d : -f2-`
    if [ $exitcode -ne 0 ] || [ -z "$link" ];then
        emailnotify  "devops@mitsogo.com,itops@mitsogo.com" \
                "Expiring Secrets - Azure AD Apps" \
                "Report for Azure AD apps secrets expiring in next 7 days" \
                --mailfrom "devops-reports@hexnodemdmnotifications.com" \
                --attachment "$ad_report"
    else    
        
        emailnotify  "devops@mitsogo.com,itops@mitsogo.com" \
                "Expiring Secrets - Azure AD Apps" \
                "Report for Azure AD apps secrets expiring in next 7 days.\n${link}" \
                --mailfrom "devops-reports@hexnodemdmnotifications.com" 
    fi
    exitcode=$?

    if [ $exitcode -ne 0 ];then
        message "critical:error while sending email notification of expiring secrets Azure AD apps"
    else
        message "info:successfully delivered email notification of expiring secrets Azure AD apps"
        mv $ad_report reports/
    fi
else
    message "no expiring certificate found"
fi
exit $exitcode


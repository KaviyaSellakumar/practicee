#!/bin/bash

scriptpid=$$

if [ $(id -u ) -ne 0 ];then
    echo "needs root permission to execute. run with sudo"
    exit 1
fi

projectdir="/var/www/html/mobarmour"
workdir="/opt/mitsogo"
SettingsFile="${projectdir}/mdmproject/settings/production.py"
LocalSettingsFile="${projectdir}/mdmproject/settings/local.py"
historyfile="/home/mitsadmin/updationhistory"
init_time=$(date +%Y%m%d%H%M%S)
outputdir="/home/mitsadmin/updationoutput/${init_time}"
scriptoutputfile="${outputdir}/qa_updater.log"
scriptlockfile="/tmp/updater_qaupdate.lock"
GIT_REMOTE=origin

export PAGER=

dbhost=$(grep "'HOST':" $SettingsFile|awk -F ':' '{print $2}'|sed "s/[, ']//g")
dbhost=${dbhost:-$dbhostoverride}

dbport=$(grep "'PORT':" $SettingsFile|awk -F ':' '{print $2}'|sed "s/[, ']//g")
dbport=${dbport:-$dbportoverride}

dbuser=$(grep "'USER':"  $SettingsFile|awk -F ':' '{print $2}'|sed "s/[, ']//g")
dbuser=${dbuser:-$dbuseroverride}

dbname=$(grep "'NAME':"  $SettingsFile|awk -F ':' '{print $2}'|sed "s/[, ']//g")
dbname=${dbname:-$dbnameoverride}

dbpasswd=$(grep "'PASSWORD':"  $SettingsFile|awk -F ':' '{print $2}'|sed "s/[, ']//g")
dbpasswd=${dbpasswd:-$dbpasswdoverride}


rundbquery(){

    local output

    if [ "$2" ];then
        output=$(PGPASSWORD=$dbpasswd psql -h $dbhost -p $dbport -U $dbuser -d "$2" -t -c "$1")
    else
        output=$(PGPASSWORD=$dbpasswd psql -h $dbhost -p $dbport -U $dbuser -d $dbname -t -c "$1")
    fi
    echo $output

}

makedbdump() {
    PGPASSWORD=$dbpasswd pg_dump -Fc -h $dbhost -p $dbport -U $dbuser $dbname
}

message() {
    echo "$(date +'%Y-%m-%d %H:%M:%S') $portalname:$1"|tee -a $scriptoutputfile

}

createDBbackup() {
    message "info:dumping database of portal"
    makedbdump > $1
    
    EXITVALUE=$?
    if [ $EXITVALUE != 0 ]; then
        message "critical:error while creating db backup. Exit value [$EXITVALUE]"
        exit $EXITVALUE
    fi

    message "info:hexnodemdm db backup successfully created."

}

handleceleryblock() {
    celery="$1"
    ${workdir}/listceleryqueue.py -v|tee -a $scriptoutputfile

	message "info:forcefully killing celery worker process"
    celery_pids=$(ps -fu apache|grep "${celery}-w1.pid"|awk '{print $2}'|sort -r)
    for pid in $celery_pids
        do
            echo|tee -a $scriptoutputfile
            message "debug:listing files opened by celery process with pid $pid"
            lsof -p $pid|tee -a $scriptoutputfile

            message "info:killing celery process $pid"
            ps -ef|awk '{ if ($2 == '$pid' ) {print $0}}'
            kill -9 $pid
        done

}

reloadcheck() {

    if [ $2 -eq 0 ];then
        message "info:successfully restarted $1 service"
    elif [ $2 -eq 124 ];then
        message "info:timeout occured while restarting $1 service"
        service_timeout_error="${1},${service_timeout_error}"

        if [ "$1" = "celery" ] || [ "$1" = "celerylow" ] || [ "$1" = "celeryhigh" ];then
            handleceleryblock "$1"
            message "info:retrying $3 of $1 service"
            service $1 $3
        fi

    else
        message "info:failed to restart $1 service"
        service_restart_error="${1},${service_restart_error}"
    fi

}

manage_service_status() {

    if [ "$service_status_enabled" = 0 ];then
        message "info:service_status already disabled in portal"
        return 0
    fi

    if [ "$1" = "enable" ];then
        message "info:enabling service_status notification in portal"
        message "info:removing service_status.disable file in portal"
        rm -f "${workdir}/service_status.disable"

    elif [ "$1" = "disable" ];then
        message "info:disabling service_status notification in portal"
        message "info:creating service_status.disable file in portal"
        touch "${workdir}/service_status.disable"
    else
        message "info:unknown argument"
    fi

}

reloadservices() {

    manage_service_status "disable"

    if [ "$1" = 'all' ] || [ "$1" = 'httpd' ];then
        if httpd -t ;then

            if [ "$IGNOREACCESS" = 'true' ];then
                message "info:reloading apache service for portal"
                timeout 5m service httpd "$2"
            else
                message "info:restarting apache service for portal"
                timeout 5m service httpd "$2"
            fi
            reloadcheck "httpd" $? "$2"
        else
            message "critical:syntax error in apache configuration"
            message "critical:skipping apache reload due to error"
        fi
    fi

    message "info:setting folder permission for logs folder"
    chown apache:apache -R "${projectdir}/logs/"

    if [ "$1" = 'all' ] || [ "$1" = 'agentserver' ];then
        if [ -f /etc/init.d/agentserver ];then
            timeout 5m service agentserver "$2"
            reloadcheck "agentserver" $? "$2"
        else
            message "warning:agentserver disabled in portal"
        fi
    fi

    if [ "$1" = 'all' ] || [ "$1" = 'celerybeat' ];then
        if [ -f /etc/init.d/celerybeat ];then
            timeout 5m service celerybeat "$2"
            reloadcheck "celerybeat" $? "$2"
        else
            message "warning:celerybeat service disabled in portal"
        fi
    fi

    if [ "$1" = 'all' ] || [ "$1" = 'celery' ];then
        if [ -f /etc/init.d/celery ];then
            timeout 10m service celery "$2"
            reloadcheck "celery" $? "$2"
        else
            message "warning:celery service disabled in portal"
        fi
    fi

    if [ "$1" = 'all' ] || [ "$1" = 'celerylow' ];then
        if [ ! -f /etc/init.d/celerylow ];then
            message "warning:celerylow service not present"
        else
            message "info:celerylow service present in the portal"
            timeout 10m service celerylow "$2"
            reloadcheck "celerylow" $? "$2"
        fi
    fi

    if [ "$1" = 'all' ] || [ "$1" = 'celeryhigh' ];then
        if [ ! -f /etc/init.d/celeryhigh ];then
            message "warning:celeryhigh service not present"
        else
            message "info:celeryhigh service present in the portal"
            timeout 10m service celeryhigh "$2"
            reloadcheck "celeryhigh" $? "$2"
        fi
    fi

    manage_service_status "enable"

}

createRESbackup() {
    message "info:starting resource backup"
    local cwd=$PWD
    cd $projectdir

    git log -1  > changeset.txt

    modifiedfiles=$(git ls-files -m)

    if [ ! -z "$modifiedfiles" ];then
        message "info:listing custom modified files in portal"
        git ls-files -m

        mkdir -p "/tmp/custommodifications"
        for file in $modifiedfiles;
            do
                folder=$(dirname $file)
                mkdir -v -p "/tmp/custommodifications/${folder}"
                cp -v "${projectdir}/${file}" "/tmp/custommodifications/${file}"
            done
    else
        message "info:no custom modifications for portal"
    fi

    tar -zcf $1 --ignore-failed-read -C ${projectdir} --exclude backup --exclude exports resource changeset.txt \
                -C ${projectdir}/base/ migrations/  \
                -C ${projectdir}/mdmproject/settings/ production.py local.py \
                -C ${projectdir}/media/ img \
                -C ${projectdir}/static/ mac_app \
                -C /etc/httpd/conf.d/ production.conf \
                -C /etc/default celery celerylow celeryhigh celerybeat agentserver \
                -C /tmp custommodifications

    EXITVALUE=$?

    if [ $EXITVALUE != 0 ] && [ $EXITVALUE != 1 ];then
        message "critical:Error while creating resource backup. Exit value [$EXITVALUE]"
        exit $EXITVALUE
    fi

    rm -rf /tmp/custommodifications
    message "info:hexnodemdm resource backup successfully created."
    cd $cwd

}

checkServices() {
    message "info:checking for error while service restart"

    service_error=''

    message "info:checking apache service"

    apache_zombie=$(ps -fu apache|awk '{ if ( $8 == "server" || $8 == "mobarmour" || $8 == "api" || $8 == "windows" || $8 == "androidcheckin" || $8 == "android" || $8 == "/usr/sbin/httpd" ) { print $3 } }'|grep -c ^1$)

    if [ $apache_zombie -gt 0 ];then
        message "critical:apache zombie process for portal"
        service_error=${service_error}",apache"
    fi

    if [ -f /etc/init.d/celerybeat ];then
        if [ $(ps -o args= -u apache|grep -c 'celerybeat.pid') -eq 0 ];then
            message "critical:celerybeat exited for portal"
            service_error="${service_error},celerybeat"
        fi
    fi

    if [ -f /etc/init.d/agentserver ];then

        if [ $(ps -o args= -u apache|grep -c 'adserver_start') -eq 0 ];then
            message "critical:agnetserver exited for portal"
            service_error="${service_error},adagent"
        fi
    fi

    # adding sleep to give celery adequate time to restart completely
    sleep 15

    if [ -f /etc/init.d/celery ];then
        if [ $(ps -o args= -u apache|grep -c 'celery-w1.pid') -eq 0 ];then
            message "critical:celery exited for portal"
            service_error="${service_error},celery"
        fi
    fi

    if [ -f /etc/init.d/celerylow ];then
        if [ $(ps -o args= -u apache|grep -c 'celerylow-w1.pid') -eq 0 ];then
            message "critical:celerylow exited for portal"
            service_error="${service_error},celerylow"
        fi
    fi

    if [ -f /etc/init.d/celeryhigh ];then
        if [ $(ps -o args= -u apache|grep -c 'celeryhigh-w1.pid') -eq 0 ];then
            message "critical:celeryhigh exited for portal"
            service_error="${service_error},celeryhigh"
        fi
    fi

}

cleanup() {
    message "info:removing lock file"
    rm -f $scriptlockfile
}

cd $projectdir

if [ ! -d $outputdir ];then
    echo "creating $outputdir directory"
    mkdir -p  $outputdir
fi

portalname=$(hostname)

if [ -f "${workdir}/service_status.disable" ];then
    service_status_enabled=0
else
    service_status_enabled=1
fi

if [ "$1" ] && [ "$1" = "clean" ];then

    # environment variables to be supplied to script during non interacive exection. INTERACTIVE='false'
    # CLEAR_PROCEED : proceed with clearing
    # CLEAR_REVERT_PROCEED : clear custom modification in portal
    # PORTALNAME : portalname 
    # BRANCH : branch name to be updated
    # COMMIT_SHA : commit id to be updated. ignore if wanted to update to latest version of the branch
    # GIT_USER : git username
    # GIT_PASSWORD : git password
    # SKIP_BACKUP : to skip backup creation set SKIP_BACKUP to 'true'
    # MDMUSERNAME : optional (username for mdm portal)
    # NAME : optional (name for technician in mdm portal)
    # MDMPASSWORD : optional (password for mdm portal)

    message "info:setting portal from scratch by clearing data"
    message "info:job initiated by technician : ${technician:-'unknown technician'}"

    if [ "$INTERACTIVE" = 'false' ];then
        CLEAR_PROCEED=${CLEAR_PROCEED:-'Yes'}
        message "info:clearing portal data"
    else
        read -p "Do you want to clear the portal data? (Yes/No) : " CLEAR_PROCEED
    fi

    if [ "$CLEAR_PROCEED" != 'Yes' ];then
        message "aborting portal data clearing in $portalname"
        exit 1
    fi

    modified=$(git ls-files -m)

    if [ ! -z "$modified" ];then
        message "warning:custom modifications exists for following files in $portalname"
        git ls-files -m
        git ls-files -m >> $scriptoutputfile

        message "info:listing custom modifications"
        PAGER= git diff
        git diff >> $scriptoutputfile

        if [ "$INTERACTIVE" = 'false' ];then
            CLEAR_REVERT_PROCEED=${CLEAR_REVERT_PROCEED:-'Yes'}
        else
            read -p "Continue the update process by reverting the above custom modifications? press (Yes/No) : " CLEAR_REVERT_PROCEED
        fi

        if [ "$CLEAR_REVERT_PROCEED" != "Yes" ];then
            message "info:aborting portal data clearing in $portalname"
            exit 1
        else
            message "info:reverting custom modifications in portal"
        fi

        git checkout .

    else
        message "info:no custom modifications in $portalname"
    fi

    if [ "$INTERACTIVE" = 'false' ];then
        RESELLER=${RESELLER:-'No'}

    else
        read -p "Do you want to set the portal as reseller portal? (Yes/No) : " RESELLER
    fi

    if [ "$RESELLER" = "Yes" ];then
        RESELLER='reseller'
        if [ "$INTERACTIVE" = 'false' ];then
            RESELLER_EMAIL=${RESELLER_EMAIL:-'None'}
        else
            read -p "Enter reseller email address : " RESELLER_EMAIL
        fi

        if [ "$RESELLER_EMAIL" = 'None' ];then
            message "warning:enter valid reseller email address"
            exit 1
        fi
    else
        message "info:not setting up as reseller portal"
        RESELLER='None'
        RESELLER_EMAIL='None'
    fi

    if [ ! -z "$JENKINS_PROXY" ];then
        message "info:setting proxy for pulling updates from gitlab.mitsogo.com"
        export https_proxy="$JENKINS_PROXY"
    else
        message "info:no proxy server available for pulling updates from gitlab.mitsogo.com"
    fi

    message "fetching updates from gitlab"

    if [ "$INTERACTIVE" = 'false' ];then
        GIT_SSL_NO_VERIFY=true git fetch --quiet https://${GIT_USER:-'user'}:${GIT_PASSWORD:-'secret'}@gitlab.mitsogo.com/mdm-v1/mobarmour.git +refs/heads/*:refs/remotes/origin/* +refs/tags/*:refs/tags/*
    else
        message "info:supply your username and token password during the prompt"
        GIT_SSL_NO_VERIFY=true git fetch https://gitlab.mitsogo.com/mdm-v1/mobarmour.git +refs/heads/*:refs/remotes/origin/* +refs/tags/*:refs/tags/*
    fi

    if [ "$?" -gt 0 ];then
        message "critical:error while fetching updates from gitlab.mitsogo.com"
        exit 1
    fi

    message "info:unsetting proxy for pulling updates from gitlab.mitsogo.com"
    export https_proxy=""

    branch=$(git rev-parse --abbrev-ref HEAD)
    current_sha=$(git rev-parse HEAD)

    message "info:current branch : $branch"
    message "info:current commit : $current_sha"

    if [ "$INTERACTIVE" = 'false' ];then
        if [ -z "$PORTALNAME" ];then
            message "critical:portalname is empty"
            exit 2
        else
            message "info:portalname is $PORTALNAME"
        fi

        if [ -z "$BRANCH" ];then
            message "critical:branch is empty"
            exit 2
        else
            message "info:branch is $BRANCH"
        fi

    else
        read -p "Enter portalname : " PORTALNAME
        read -p "Enter branch name to update : " BRANCH
        read -p "Enter commit SHA if needed to update to specific commit else skip : " COMMIT_SHA
    fi

    if [ -z "$COMMIT_SHA" ];then
        COMMIT_SHA=$(git log -1 ${GIT_REMOTE}/${BRANCH} --format=%H)
    else
        message "info:checking commit $COMMIT_SHA"

        if git log ${GIT_REMOTE}/${BRANCH} --format=%H|grep -q $COMMIT_SHA ;then
            message "info:commit $COMMIT_SHA included in $BRANCH"
        else
            message "critical:commit $COMMIT_SHA not included in $BRANCH"
            exit 1
        fi
    fi

    message "info:checking lock file"

    if [ -f $scriptlockfile ];then
        processid=$(cat $scriptlockfile)

        if [ -n "$(ps -p $processid -o pid=)" ];then
            message "critical:another instance of updation script is running"
            exit 52
        fi
    fi

    message "info:creating lock file"
    echo "$scriptpid" > $scriptlockfile

    message "info:stopping services in $portalname"

    reloadservices "httpd" "stop"
    reloadservices "agentserver" "stop"
    reloadservices "celerybeat" "stop"
    reloadservices "celery" "stop"
    reloadservices "celerylow" "stop"
    reloadservices "celeryhigh" "stop"

    message "info:stopping active database connections in $portalname"

    rundbquery "SELECT pg_terminate_backend(pg_stat_activity.pid) FROM pg_stat_activity WHERE datname = current_database() AND pid <> pg_backend_pid();"

    if [ "$SKIP_BACKUP" = 'true' ];then
        message "warning:skipping backup creation"
    else
        message "info:creating backup of database"
        createDBbackup "${outputdir}/${portalname}_hexnodedb_$(date +'%Y%m%d%H%M%S').dump"

        message "info:database backup available at ${outputdir}/${portalname}_hexnodedb_$(date +'%Y%m%d%H%M%S').dump"

        message "info:creating backup of resources"
        createRESbackup "${outputdir}/${portalname}_hexnoderesource_$(date +'%Y%m%d%H%M%S').tar.gz"

        message "info:resource backup available at ${outputdir}/${portalname}_hexnoderesource_$(date +'%Y%m%d%H%M%S').tar.gz"
    fi

    message "info:clearing database in $portalname"
    rundbquery "drop database $dbname" "postgres"

    rundbquery "create database $dbname" "postgres"

    if [ -d ${projectdir}/base/migrations ];then

        message "info:deleting old migrations for portal $portalname"
        rm -rf ${projectdir}/base/migrations
    fi

    message "info:updating portal code"

    message "info:updating to branch : $BRANCH"
    message "info:updating to commit : $COMMIT_SHA"

    git checkout "$BRANCH" -f
    git reset --hard  "$COMMIT_SHA"


    staticCdnMode=$(grep "^IS_STATIC_CDN_MODE[ ]*=" $LocalSettingsFile |tail -n 1|awk -F '=' '{print $2}'|sed s/' '//g)
    if [ "$staticCdnMode" = "True" ];then
        message "info:static cdn mode is enabled in $LocalSettingsFile"
        message "info:enabling cdn mode in $SettingsFile"

        if grep -q '^IS_STATIC_CDN_MODE[ ]*=' $SettingsFile ;then
            sed -i s/"^IS_STATIC_CDN_MODE[ ]*=.*$"/"IS_STATIC_CDN_MODE = True"/ $SettingsFile
            message "info:changed IS_STATIC_CDN_MODE to True"
        else
            echo 'IS_STATIC_CDN_MODE = True' >> $SettingsFile
            message "info:added IS_STATIC_CDN_MODE to True"
        fi
    else
        message "info:static cdn mode is disabled in $LocalSettingsFile"
        message "info:disabling cdn mode in $SettingsFile"

        if grep -q '^IS_STATIC_CDN_MODE[ ]*=' $SettingsFile ;then
            sed -i s/"^IS_STATIC_CDN_MODE[ ]*=.*$"/"IS_STATIC_CDN_MODE = False"/ $SettingsFile
            message "info:changed IS_STATIC_CDN_MODE to False"
        else
            echo 'IS_STATIC_CDN_MODE = False' >> $SettingsFile
            message "info:added IS_STATIC_CDN_MODE to False"
        fi
    fi

    message "info:starting portal setup"

    sh ${projectdir}/configure_reserve.sh

    MDMUSERNAME=${MDMUSERNAME:-'jibin@mitsogo.com'}
    MDMPASSWORD=${MDMPASSWORD:-'Password1'}
    NAME=${NAME:-'jibin'}

    sh ./configure_aws.sh "$MDMUSERNAME" "$MDMPASSWORD" "$MDMUSERNAME" "$NAME" "$PORTALNAME" "" "$RESELLER" "$RESELLER_EMAIL" "$RESELLER_EMAIL" "$ACCOUNT_ID"

    if [ -f /etc/init.d/celerylow ];then
        service celerylow restart
    fi

    service rsyslog restart

    message "info:portal setup completed"

    message "info:portal name    : $PORTALNAME"
    message "info:username       : $MDMUSERNAME"
    message "info:password       : $MDMPASSWORD"
    message "info:portal branch  : $BRANCH"
    message "info:portal commit  : $COMMIT_SHA"
    message "info:reseller type  : $RESELLER"
    message "info:reseller email : $RESELLER_EMAIL"

    cat <<EOF >> $historyfile
######################################################
date:$(date)
current details are:$portalname:$branch:$current_sha
techinician:${technician:-hexnodemdm qa_update script}
updated details are:$PORTALNAME:$BRANCH:$COMMIT_SHA
EOF

    checkServices

    if [ ! -z $service_error ];then
        message "critical:error in service restart for $service_error"
        cleanup
        exit 64
    fi

else
    
    # environment variables to be supplied to script during non interacive exection. INTERACTIVE='false'
    # UPDATE_BRANCH : branch name to be updated
    # COMMIT_SHA : commit id to update
    # GIT_USER : git username
    # GIT_PASSWORD : git password
    # UPDATE_BRANCH : update branch
    # UPDATE_PROCEED : proceeding with updates after listing changes in the update
    # REVERT_PROCEED : proceed with update even if custom modifications exists
    # SKIP_BACKUP : to skip backup creation set SKIP_BACKUP to 'true'
    # JSON_PROCEED : skip checking of json changes during update
    # SKIP_PRESCRIPT : skip pre script execution
    # SKIP_POSTSCRIPT : skip post script execution

    portalname=$(rundbquery "select nat_server from base_serversettings;")
    DJANGO_UPDATE_STATUS=$(python -c "import django; from distutils.version import LooseVersion; print(LooseVersion(django.get_version()) >= LooseVersion('1.7'))")

    if [ -z $portalname ];then
        message "critical:unable to access database for portal $(hostname)"
        message "critical:aborting updation in portal $(hostname)"
        exit 1
    fi

    branch=$(git rev-parse --abbrev-ref HEAD)
    current_sha=$(git rev-parse HEAD)

    if [ ! -z "$JENKINS_PROXY" ];then
        message "info:setting proxy for pulling updates from gitlab.mitsogo.com"
        export https_proxy="$JENKINS_PROXY"
    else
        message "info:no proxy server available for pulling updates from gitlab.mitsogo.com"
    fi

    message "info:fetching updates from gitlab"

    if [ "$INTERACTIVE" = 'false' ];then
        GIT_SSL_NO_VERIFY=true git fetch --quiet https://${GIT_USER:-'user'}:${GIT_PASSWORD:-'secret'}@gitlab.mitsogo.com/mdm-v1/mobarmour.git +refs/heads/*:refs/remotes/origin/* +refs/tags/*:refs/tags/*
    else
        message "info:supply your username and token password during the prompt"
        GIT_SSL_NO_VERIFY=true git fetch https://gitlab.mitsogo.com/mdm-v1/mobarmour.git +refs/heads/*:refs/remotes/origin/* +refs/tags/*:refs/tags/*
    fi

    if [ "$?" -gt 0 ];then
        message "info:error while fetching updates from gitlab.mitsogo.com"
        exit 1
    fi

    message "info:unsetting proxy for pulling updates from gitlab.mitsogo.com"
    export https_proxy=""

    message "info:name of the current branch : $branch"
    message "info:current commit : $current_sha"

    if [ "$INTERACTIVE" = 'false' ];then
        if [ -z "$UPDATE_BRANCH" ];then
            message "info:branch name to be updated is empty"
            exit 1
        fi

    else
        read -p "Enter the branch name to which it should be updated : " UPDATE_BRANCH
    fi

    message "info:updating to branch : $UPDATE_BRANCH"

    if [ -z "$COMMIT_SHA" ];then
        updated_sha=$(git log -1 ${GIT_REMOTE}/${UPDATE_BRANCH} --format=%H)
    else
        message "info:checking commit $COMMIT_SHA"

        if git log ${GIT_REMOTE}/${UPDATE_BRANCH} --format=%H|grep -q $COMMIT_SHA ;then
            message "info:commit $COMMIT_SHA included in $UPDATE_BRANCH"
        else
            message "info:commit $COMMIT_SHA not included in $UPDATE_BRANCH"
            exit 1
        fi

        message "info:updating to commit : $COMMIT_SHA"
        updated_sha=$COMMIT_SHA
    fi

    if [ "$current_sha" = "$updated_sha" ];then
        message "info:$portalname already at the latest version"
        exit 0
    fi

    modified=$(git ls-files -m)

    message "info:files modified in this version update"

    PAGER= git diff --name-only "$current_sha" "$updated_sha"
    git diff --name-only "$current_sha" "$updated_sha" >> $scriptoutputfile

    if [ "$INTERACTIVE" = 'false' ];then
        UPDATE_PROCEED=${UPDATE_PROCEED:-'Yes'}
    else
        read -p "The above files will be updated in this version update. Proceed? (Yes/No) : " UPDATE_PROCEED
    fi

    if [ "$UPDATE_PROCEED" != "Yes" ]; then
        message "critical:aborting updation in portal $portalname"
        exit 1
    fi

    if [ ! -z "$modified" ];then
        message "warning:custom modifications exists for following files in portal $portalname"
        git ls-files -m
        git ls-files -m >> $scriptoutputfile

        message "info:printing the custom modifications"
        PAGER= git diff
        git diff >> $scriptoutputfile

        if [ "$INTERACTIVE" = 'false' ];then
            REVERT_PROCEED=${REVERT_PROCEED:-'No'}
        else
            read -p "Continue the update process by reverting the above custom modifications? press (Yes/No). Make sure that customer has commited the above modifications in the repository : " REVERT_PROCEED
        fi

        if [ "$REVERT_PROCEED" != "Yes" ];then
            message "critical:aborting updation in portal $portalname"
            exit 1
        else
            message "info:updating portal by reverting custom modifications"
        fi

        git checkout .

    else
        message "info:no custom modifications in $portalname"
    fi

    if [ $(git diff --name-only "$current_sha" "$updated_sha"|grep -c 'base/fixtures/mdm_initial_data.json') -eq 1 ];then

        message "info:modification in base/fixtures/mdm_initial_data.json"

        PAGER= git diff "$current_sha" "$updated_sha" base/fixtures/mdm_initial_data.json
        git diff "$current_sha" "$updated_sha" base/fixtures/mdm_initial_data.json >> $scriptoutputfile
    fi

    if [ $(git diff --name-only "$current_sha" "$updated_sha"|grep -c 'base/fixtures/initial_data.json') -eq 1 ];then

        message "info:modification in base/fixtures/initial_data.json"

        PAGER= git diff "$current_sha" "$updated_sha" base/fixtures/initial_data.json
        git diff "$current_sha" "$updated_sha" base/fixtures/initial_data.json >> $scriptoutputfile

        if [ $(git ls-tree --name-only -r "$updated_sha"|grep -c 'base/fixtures/mdm_initial_data.json') -eq 1 ];then
            message "info:mdm_initial_data.json file exists in commit"
            JSON_PROCEED="Yes"
        else

            if [ "$INTERACTIVE" = 'false' ];then
                JSON_PROCEED=${JSON_PROCEED:-'No'}
            else
                read -p "Continue the update process by ignoring modifications in initial_data.json? press (Yes/No). Please validate json changes before proceeding : " JSON_PROCEED
            fi
        fi

        if [ "$JSON_PROCEED" != "Yes" ];then
            message "info:please contact devops team to handle initial_data.json modifications"
            message "critical:aborting updation in portal $portalname"
            exit 2
        else
            message "info:proceeding update by ignoring initial_data.json changes"
        fi

    fi

    message "info:checking lock file"

    if [ -f $scriptlockfile ];then
        processid=$(cat $scriptlockfile)

        if [ -n "$(ps -p $processid -o pid=)" ];then
            message "critical:another instance of updation script is running"
            exit 52
        fi
    fi

    message "info:creating lock file"
    echo "$scriptpid" > $scriptlockfile

    message "info:stopping sevices"
    timeout 120 service celery stop

    exitcode=$?

    if [ $exitcode -eq 0 ];then
        message "info:successfully stopped celery service"

    elif [ $exitcode -eq 124 ];then
        message "info:timeout occured while stopping celery service"
        ${workdir}/listceleryqueue.py -v|tee -a $scriptoutputfile

        message "info:forcefully killing celery worker process"
        celery_pids=$(ps -fu apache|grep 'celery-w1.pid'|awk '{print $2}'|sort -r)
        for pid in $celery_pids
            do
                echo|tee -a $scriptoutputfile
                message "debug:listing files opened by celery process with pid $pid"
                lsof -p $pid|tee -a $scriptoutputfile

                message "info:killing celery process $pid"
                ps -ef|awk '{ if ($2 == '$pid' ) {print $0}}'
                kill -9 $pid
            done
    fi

    service celerybeat stop
    service agentserver stop
    service httpd stop
    if [ -f /etc/init.d/celerylow ];then
        timeout 120 service celerylow stop
    fi

    if [ "$SKIP_BACKUP" = 'true' ];then
        message "info:skipping backup creation"
    else
        message "info:creating backup of database"
        createDBbackup "${outputdir}/${portalname}_hexnodedb_$(date +'%Y%m%d%H%M%S').dump"

        message "info:database backup available at ${outputdir}/${portalname}_hexnodedb_$(date +'%Y%m%d%H%M%S').dump"

        message "creating backup of resources"
        createRESbackup "${outputdir}/${portalname}_hexnoderesource_$(date +'%Y%m%d%H%M%S').tar.gz"

        message "info:resource backup available at ${outputdir}/${portalname}_hexnoderesource_$(date +'%Y%m%d%H%M%S').tar.gz"
    fi

    if [ $(git diff --name-only "$current_sha" "$updated_sha"|grep -c 'base/models.py') -eq 1 ];then

        message "info:deleting old migrations for portal $portalname"

        rm -rf ${projectdir}/base/migrations
 
        if [ "$DJANGO_UPDATE_STATUS" = "False" ];
        then
            rundbquery "delete from south_migrationhistory where app_name ='base';"
            python manage.py schemamigration base --initial
            
        else
            rundbquery "delete from django_migrations  where app='base';"
            python manage.py makemigrations base
        fi
        python manage.py migrate base --fake
        message "info:performed initial migrations for portal $portalname"
    fi
    if [ "$SKIP_PRESCRIPT" = 'true' ];then
        message "info:skipping pre scripts in portal"
    else
        message "info:running pre scripts in portal"
        prescript_error=''

        message "info:creating directory for pre scripts"
        mkdir -p ${outputdir}/pre_scripts

        message "info:clearing old pre scripts in pre_scripts directory"
        rm -f ${outputdir}/pre_scripts/*

        message "info:copying pre scripts to directory"
        cp ${projectdir}/scripts/pre_scripts/* ${outputdir}/pre_scripts/

        pre_script_modified=$(git diff --name-only --diff-filter=r $current_sha $updated_sha scripts/pre_scripts/)
        for pre_script in $pre_script_modified
            do
                message "info:updating changes in pre script $pre_script"
                git show ${updated_sha}:${pre_script} > ${outputdir}/pre_scripts/$(basename "$pre_script")
            done

        pre_script_removed=$(git diff --name-only --diff-filter=R $current_sha $updated_sha scripts/pre_scripts/)
        for pre_script in $pre_script_removed
            do 
                message "info:removing pre script $pre_script"
                rm ${outputdir}/pre_scripts/$(basename "$pre_script")
            done

        message "info:changing permission for pre_scrips folder"
        chmod -R 755 ${outputdir}/pre_scripts/

        for script in $(ls ${outputdir}/pre_scripts/|grep -E '.*.py$')
            do
                message "info:executing $script"
                python ${outputdir}/pre_scripts/${script}  &> ${outputdir}/${script%.py}_output.txt

                if [ $? != 0 ];then
                    message "critical:error while executing $script in portal"
                    prescript_error=${prescript_error}",${script}"
                else
                    message "info:successfully executed $script in portal"
                fi

                cat ${outputdir}/${script%.py}_output.txt
                cat ${outputdir}/${script%.py}_output.txt >> $scriptoutputfile
                echo "##################################################################"
                echo

                if [ ! -z $prescript_error ];then
                    message "critical:prescript error $prescript_error"
                    cleanup
                    exit 58
                fi
            done
    fi

    message "info:updating to commit $updated_sha in branch $UPDATE_BRANCH for portal $portalname"
    git checkout "$UPDATE_BRANCH" -f

    if [ $? -ne 0 ];then
        message "critical:error while updating to branch $UPDATE_BRANCH"
        cleanup
        exit 59
    else
        message "info:successfully updated to branch $UPDATE_BRANCH"
    fi

    git reset --hard  "$updated_sha"

    if [ $(git diff --name-only "$current_sha" "$updated_sha"|grep -c 'base/models.py') -eq 1 ];then
        message "info:creating schemamigration for portal $portalname"
        if [ "$DJANGO_UPDATE_STATUS" = "False" ];
        then
            python manage.py schemamigration base --auto

            message "info:migrating database for portal $portalname"
            python manage.py migrate base --no-initial-data
        else
            python manage.py makemigrations base
            message "info:migrating database for portal $portalname"
            python manage.py migrate base
        fi

    fi

    if [ -f base/fixtures/mdm_initial_data.json ];then
        message "info:mdm_initial_data present in the portal. loading initial_data.json"
        python manage.py loaddata base/fixtures/initial_data.json
    else
        message "info:mdm_initial_data not present in the portal. skipping loading initial_data.json"
    fi

    staticCdnMode=$(grep "^IS_STATIC_CDN_MODE[ ]*=" $LocalSettingsFile |tail -n 1|awk -F '=' '{print $2}'|sed s/' '//g)
    if [ "$staticCdnMode" = "True" ];then
        message "info:static cdn mode is enabled in $LocalSettingsFile"
        message "info:enabling cdn mode in $SettingsFile"

        if grep -q '^IS_STATIC_CDN_MODE[ ]*=' $SettingsFile ;then
            sed -i s/"^IS_STATIC_CDN_MODE[ ]*=.*$"/"IS_STATIC_CDN_MODE = True"/ $SettingsFile
            message "info:changed IS_STATIC_CDN_MODE to True"
        else
            echo 'IS_STATIC_CDN_MODE = True' >> $SettingsFile
            message "info:added IS_STATIC_CDN_MODE to True"
        fi

        message "info:overriding SKIP_COMPRESS value $SKIP_COMPRESS to true since static cdn mode is enabled"
        SKIP_COMPRESS='true'
    else
        message "info:static cdn mode is disabled in $LocalSettingsFile"
        message "info:disabling cdn mode in $SettingsFile"

        if grep -q '^IS_STATIC_CDN_MODE[ ]*=' $SettingsFile ;then
            sed -i s/"^IS_STATIC_CDN_MODE[ ]*=.*$"/"IS_STATIC_CDN_MODE = False"/ $SettingsFile
            message "info:changed IS_STATIC_CDN_MODE to False"
        else
            echo 'IS_STATIC_CDN_MODE = False' >> $SettingsFile
            message "info:added IS_STATIC_CDN_MODE to False"
        fi
    fi
    
    if [ "$SKIP_COMPRESS" = 'true' ];then
        message "info:skipping compressing static files in portal $portalname"
    else
        message "info:compressing static files in portal $portalname"
        python manage.py compress -f > /dev/null
    fi

    message "info:compiling python code in portal $portalname"
    python -m compileall ./ >/dev/null
    
    message "info:changing folder ownership in portal $portalname"
    chown -R apache:apache logs resource static media celery 

    if [ "$SKIP_PRERESTARTSCRIPT" = 'true' ];then
        message "info:skipping pre restart scripts in portal"
    else
        message "info:running pre restart scripts in portal"
        for script in $(ls ${projectdir}/scripts/pre_restart_scripts/|grep -E '.*.py$')
            do
                message "info:checking script execution $script"
                script_status=$(rundbquery "select value from base_globalsettings where key='$script'")

                if [ "$script_status" = '0' ];then
                    message "info:script $script already executed successfully"
                else
                    message "info:executing $script"
                    python ${projectdir}/scripts/pre_restart_scripts/${script} &> ${outputdir}/${script%.py}_output.txt

                    if [ $? != 0 ];then
                        message "info:error while executing $script in portal"
                        postscript_error=${postscript_error}",${script}"
                    else
                        message "info:successfully executed $script in portal"
                    fi

                    cat ${outputdir}/${script%.py}_output.txt
                    cat ${outputdir}/${script%.py}_output.txt >> $scriptoutputfile
                    echo "##################################################################"
                    echo
                fi

            done 
    fi

    message "info:restarting sevices for portal"
    reloadservices "all" "restart"

    if [ "$SKIP_POSTSCRIPT" = 'true' ];then
        message "info:skipping post scripts in portal"
    else
        message "info:running post scripts in portal"

        for script in $(ls ${projectdir}/scripts/post_scripts/|grep -E '.*.py$')
            do
                message "info:checking script execution $script"
                script_status=$(rundbquery "select value from base_globalsettings where key='$script'")

                if [ "$script_status" = '0' ];then
                    message "info:script $script already executed successfully"
                else
                    message "info:executing $script"
                    python ${projectdir}/scripts/post_scripts/${script} &> ${outputdir}/${script%.py}_output.txt

                    if [ $? != 0 ];then
                        message "info:error while executing $script in portal"
                        postscript_error=${postscript_error}",${script}"
                    else
                        message "info:successfully executed $script in portal"
                    fi

                    cat ${outputdir}/${script%.py}_output.txt
                    cat ${outputdir}/${script%.py}_output.txt >> $scriptoutputfile
                    echo "##################################################################"
                    echo
                fi

            done 

    fi
    message "info:hot reloading django stack in portal $portalname"
    nohup ${projectdir}/djangoreloader "https://${portalname}/enroll/" > /tmp/loadtime 2>&1 &
    
    cat <<EOF >> $historyfile
######################################################
date:$(date)
current details are:$portalname:$branch:$current_sha
techinician:${technician:-hexnodemdm qa_update script}
updated details are:$portalname:$UPDATE_BRANCH:$updated_sha
EOF

    checkServices

    if [ ! -z $service_error ];then
        message "critical:error in service restart for $service_error"
        cleanup
        exit 64
    fi

    if [ ! -z $postscript_error ];then
        message "critical:error in post scripts $postscript_error execution. Please check with developers immediately"
        cleanup
        exit 64
    fi
fi

cleanup

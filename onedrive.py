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

S3_BUCKET="s3://testing-hexnode"
S3_MIGRATION_BACKUP_PATH="migrations/backup/"
S3_DB_BACKUP_PATH="db/backup/"

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

    backup_migrations() {
        message "info:Backing up migration folder to S3"
        aws s3 cp "${projectdir}/base/migrations" "${S3_BUCKET}/${S3_MIGRATION_BACKUP_PATH}/$(date +%Y%m%d%H%M%S)" --recursive
        if [ $? -eq 0 ]; then
            message "info:Migration folder backed up successfully to S3"
        else
            message "critical:Failed to back up migration folder to S3"
            exit 1
        fi
    }
    backup_migrations

    backup_database() {
        message "info:Backing up database to S3"
        local db_backup_path="${S3_BUCKET}/${S3_DB_BACKUP_PATH}/$(date +%Y%m%d%H%M%S)_db_backup.dump"
        PGPASSWORD=$dbpasswd pg_dump -Fc -h $dbhost -p $dbport -U $dbuser $dbname > "$db_backup_path"
        if [ $? -eq 0 ]; then
            message "info:Database backed up successfully to S3"
        else
            message "critical:Failed to back up the database to S3"
            exit 1
        fi
    }
    backup_database

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
    
    restore_migrations() {
        message "info:Restoring migration folder from S3"
        aws s3 cp "${S3_BUCKET}/${S3_MIGRATION_BACKUP_PATH}/$(date +%Y%m%d%H%M%S)" "${projectdir}/base/migrations" --recursive
        if [ $? -eq 0 ]; then
            message "info:Migration folder restored successfully from S3"
        else
            message "critical:Failed to restore migration folder from S3"
            exit 1
        fi
    }
    restore_migrations

    restore_database() {
        message "info:Restoring database from S3"
        local db_backup_path="${S3_BUCKET}/${S3_DB_BACKUP_PATH}/$(date +%Y%m%d%H%M%S)_db_backup.dump"
        PGPASSWORD=$dbpasswd pg_restore -h $dbhost -p $dbport -U $dbuser -d $dbname < "$db_backup_path"
        if [ $? -eq 0 ]; then
            message "info:Database restored successfully from S3"
        else
            message "critical:Failed to restore the database from S3"
            exit 1
        fi
    }
    restore_database
    
    
    message "info:Running fake migrations"
    cd $projectdir 
    python manage.py migrate --fake
    if [ $? -eq 0 ]; then
        message "info:Fake migrations applied successfully"
    else
        message "critical:Failed to apply fake migrations"
        exit 1
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




-----------------------------------------------------------




      #!/bin/sh

projectdir="/var/www/html/mobarmour"
workdir="/opt/mitsogo"
SettingsFile="${projectdir}/mdmproject/settings/production.py"

dbpasswd=$(grep "'PASSWORD':" $SettingsFile|awk -F ':' '{print $2}'|sed "s/[, ']//g")

message() {
    echo "$(date +'%Y-%m-%d %H:%M:%S') $portalname:$1"

}

rundbquery() {
    local output
    output=$(PGPASSWORD=$dbpasswd psql -h $dbhost -p $dbport -U $dbuser -d $dbname -t -c "$1")
    echo $output

}

sendnotifications() {
    message "info:sending $1 notification"
    if [ "$1" = 'teams' ];then
        python ${workdir}/notify.py "teams" 0  \
                                    --subject "$portalname : $portal_ip - $2" \
                                    --message "$3 in $portalname ($portal_ip)"
    elif [ "$1" = 'mail' ];then
        python ${workdir}/notify.py "mail" 0 \
                                    --subject "$portalname : $portal_ip - $2" \
                                    --message "$3 in $portalname ($portal_ip)" \
                                    --mailto "devops-monitor@mitsogo.com" \
                                    --mailfrom "signup-notifications@hexnodemdmnotifications.com"
    else
        message "critical:unknown handler"
    fi

}

executioncheck() {
    if [ $2 -eq 0 ];then
        message "info:successfully executed $1"
    elif [ $2 -eq 124 ];then
        message "critical:timeout occured while executing $1"
        sendnotifications "mail" "critical:execution timeout during reserve setup" "timeout occured while executing $1 in portal during reserve setup"
        sendnotifications "teams" "critical:execution timeout during reserver setup" "timeout occured while executing $1 in portal during reserve setup"
    else
        message "critical:error while executing $1 with exit code $2"
        sendnotifications "mail" "critical:execution execution failed during reserve setup" "execution failed with exit code $2 while executing $1 in portal during reserve setup"
        sendnotifications "teams" "critical:execution execution failed during reserve setup" "execution failed with exit code $2 while executing $1 in portal during reserve setup"
    fi

}

portalname="reserveserver"
portal_ip=$(curl -s ipinfo.io/ip/)
portal_region="$1"
remotedbhost="$2"
remotedbname="$3"
remotedbuser="mdmuser"

cd "$projectdir"

message "**********************************************************************************************"
message "info:Hexnode MDM Reserve server configuration"


if [ "$remotedbhost" ] && [ "$remotedbname" ];then

    if [ "$remotedbhost" = 'localhost' ];then
        message "info:database host argument is localhost"
        message "info:using local postgresql server as database server"

        message "info:changing database settings for local database"
        sed -i s/"^.*'HOST':.*$"/"        'HOST': 'localhost',"/ $SettingsFile
        sed -i s/"^.*'USER':.*$"/"        'USER': 'postgres',"/ $SettingsFile
        sed -i s/"^.*'NAME':.*$"/"        'NAME': 'hexnodemdm',"/ $SettingsFile
    else
        message "info:using remote database server $remotedbhost"

        # echo 'creating database in rds server'
        # dbname_tmp=$(echo $3|tr '[A-Z]' '[a-z]')

        message "info:creating database $remotedbname in remote database server $2"
        PGPASSWORD=$dbpasswd psql -h "$remotedbhost" -U "$remotedbuser" -d postgres -c "create database \"$remotedbname\""

        if [ $? -eq 0 ];then
            message "info:successfully created database $remotedbname in remote server $remotedbhost"
            message "info:changing database settings to remote postgresql server in $SettingsFile"

            message "info:changing database host in $SettingsFile"
            sed -i s/"^.*'HOST':.*$"/"        'HOST': '$remotedbhost',"/ $SettingsFile

            message "info:changing database user in $SettingsFile"
            sed -i s/"^.*'USER':.*$"/"        'USER': '$remotedbuser',"/ $SettingsFile

            message "info:changing database name in $SettingsFile"
            sed -i s/"^.*'NAME':.*$"/"        'NAME': '$remotedbname',"/ $SettingsFile

            message "info:stopping local postgresql server"
            service postgresql stop

            message "info:disabling local postgresql server"
            chkconfig postgresql off

        else
            message "critical:error while creating database $remotedbname in remote server $remotedbhost"
            message "info:changing database settings to local postgresql server in $SettingsFile"

            message "info:changing database host in $SettingsFile"
            sed -i s/"^.*'HOST':.*$"/"        'HOST': 'localhost',"/ $SettingsFile

            message "info:changing database user in $SettingsFile"
            sed -i s/"^.*'USER':.*$"/"        'USER': 'postgres',"/ $SettingsFile

            message "info:changing database name in $SettingsFile"
            sed -i s/"^.*'NAME':.*$"/"        'NAME': 'hexnodemdm',"/ $SettingsFile

        fi
    fi

else
    message "info:missing database host argument in configuration script"
    message "info:using local postgresql database"
fi

dbuser=$(grep "'USER':" $SettingsFile|awk -F ':' '{print $2}'|sed "s/[, ']//g")
dbname=$(grep "'NAME':" $SettingsFile|awk -F ':' '{print $2}'|sed "s/[, ']//g")
dbhost=$(grep "'HOST':" $SettingsFile|awk -F ':' '{print $2}'|sed "s/[, ']//g")
dbport=$(grep "'PORT':" $SettingsFile|awk -F ':' '{print $2}'|sed "s/[, ']//g")

message "info:checking server previously configured"
check_configured=$(rundbquery "select email from auth_user where id=1;")

if [ "$check_configured" ];then
    message "critical:server already configured with mail $check_configured"
    exit 1
fi

message "info:changing BUCKET and REGION in $SettingsFile"

if [ "$portal_region" ] && [ "$portal_region" = 'eu-central-1' ];then
    sed -i s/"^REGION[ ]*=.*$"/"REGION = 'eu-central-1'"/ $SettingsFile
    sed -i s/"^BUCKET[ ]*=.*$"/"BUCKET = 'eufrahexnodemdm'"/ $SettingsFile
    message "info:changed BUCKET to eufrahexnodemdm and REGION to eu-central-1"
elif [ "$portal_region" ] && [ "$portal_region" = 'us-east-1' ];then
    sed -i s/"^REGION[ ]*=.*$"/"REGION = 'us-east-1'"/ $SettingsFile
    sed -i s/"^BUCKET[ ]*=.*$"/"BUCKET = 'hexnodemdm'"/ $SettingsFile
    message "info:changed BUCKET to hexnodemdm and REGION to us-east-1"
elif [ "$portal_region" ] && [ "$portal_region" = 'af-south-1' ];then
    sed -i s/"^REGION[ ]*=.*$"/"REGION = 'af-south-1'"/ $SettingsFile
    sed -i s/"^BUCKET[ ]*=.*$"/"BUCKET = 'cpt-hexnodemdm'"/ $SettingsFile
    message "info:changed BUCKET to cpt-hexnodemdm and REGION to af-south-1"
elif [ "$portal_region" ] && [ "$portal_region" = 'eu-west-2' ];then
    sed -i s/"^REGION[ ]*=.*$"/"REGION = 'eu-west-2'"/ $SettingsFile
    sed -i s/"^BUCKET[ ]*=.*$"/"BUCKET = 'ldn-hexnodemdm'"/ $SettingsFile
    message "info:changed BUCKET to ldn-hexnodemdm and REGION to eu-west-2"
elif [ "$portal_region" ] && [ "$portal_region" = 'ap-south-1' ];then
    sed -i s/"^REGION[ ]*=.*$"/"REGION = 'ap-south-1'"/ $SettingsFile
    sed -i s/"^BUCKET[ ]*=.*$"/"BUCKET = 'mum-hexnodemdm'"/ $SettingsFile
    message "info:changed BUCKET to mum-hexnodemdm and REGION to ap-south-1"
elif [ "$portal_region" ] && [ "$portal_region" = 'ap-southeast-1' ];then
    sed -i s/"^REGION[ ]*=.*$"/"REGION = 'ap-southeast-1'"/ $SettingsFile
    sed -i s/"^BUCKET[ ]*=.*$"/"BUCKET = 'sgp-hexnodemdm'"/ $SettingsFile
    message "info:changed BUCKET to sgp-hexnodemdm and REGION to ap-southeast-1"
elif [ "$portal_region" ] && [ "$portal_region" = 'me-central-1' ];then
    sed -i s/"^REGION[ ]*=.*$"/"REGION = 'me-central-1'"/ $SettingsFile
    sed -i s/"^BUCKET[ ]*=.*$"/"BUCKET = 'uae-hexnodemdm'"/ $SettingsFile
    message "info:changed BUCKET to uae-hexnodemdm and REGION to me-central-1"
elif [ "$portal_region" ] && [ "$portal_region" = 'ap-southeast-3' ];then
    sed -i s/"^REGION[ ]*=.*$"/"REGION = 'ap-southeast-3'"/ $SettingsFile
    sed -i s/"^BUCKET[ ]*=.*$"/"BUCKET = 'jkt-hexnodemdm'"/ $SettingsFile
    message "info:changed BUCKET to jkt-hexnodemdm and REGION to ap-southeast-3"
else
    message "info:using BUCKET hexnodemdm and REGION us-east-1 as per default"
fi

message "info:changing IS_RESERVED in $SettingsFile"

if grep -q '^IS_RESERVED[ ]*=' $SettingsFile ;then
    sed -i s/"^IS_RESERVED[ ]*=.*$"/"IS_RESERVED = True"/ $SettingsFile
    message "info:changed IS_RESERVED to True"
else
    echo "IS_RESERVED = True" >> $SettingsFile
    message "info:added variable IS_RESERVED with value True"
fi

message "info:creating migration for base app"
timeout 1800 python manage.py makemigrations base
executioncheck "makemigrations" $?

message "info:migrating apps"
timeout 1800 python manage.py migrate
executioncheck "migration" $?

message "info:loading fixtures"

message "info:loading mdm_initial_data.json"
timeout 120 python manage.py loaddata mdm_initial_data.json
executioncheck "mdm_initial_data.json loading" $?

message "info:loading access_control.json"
timeout 120 python manage.py loaddata access_control.json
executioncheck "access_control.json loading" $?

message "info:loading demo_data.json"
timeout 120 python manage.py loaddata demo_data.json
executioncheck "demo_data.json loading" $?

message "info:loading get_start_wizard.json"
timeout 120 python manage.py loaddata get_start_wizard.json
executioncheck "get_start_wizard.json loading" $?

message "info:executing scripts"

message "info:adding ios systemapps to database"
timeout 120 python scripts/setup_scripts/0001_systemappscript.py
executioncheck "0001_systemappscript.py script" $?

message "info:adding iosexpense policy to template id 11"
timeout 120 python scripts/setup_scripts/0005_iosexpense.py
executioncheck "0005_iosexpense.py script" $?

message "info:set random kiosk exit password"
timeout 120 python scripts/setup_scripts/00600_random_pwd_generation.py
executioncheck "00600_random_pwd_generation.py script" $?

message "info:update RemoteView and RemoteAssist version"
timeout 120 python scripts/setup_scripts/0030_remoteapps_versioncheck.py
executioncheck "0030_remoteapps_versioncheck.py script" $?

message "info:adding macos cis benchmark profiles with FK to template id 18 and 19"
timeout 120 python scripts/setup_scripts/00825_macos_cis_profiles.py
executioncheck "00825_macos_cis_profiles.py" $?

message "info:enabling beta features in trial"
rundbquery "update base_accesscontrol set allow_access=True;"


staticCdnMode=$(grep "^IS_STATIC_CDN_MODE[ ]*=" $SettingsFile |awk -F '=' '{print $2}'|sed s/' '//g)

if [ "$staticCdnMode" = "True" ];then
    message "info:static cdn mode is enabled in portal"
    message "info:skipping compression of static files"
else
    message "info:compressing static files"
    timeout 300 python manage.py compress -f > /dev/null
    executioncheck "django compress" $?
fi

message "info:compiling python files"
python -m compileall  ./ > /dev/null


message "info:changing folder ownership"
chown apache:apache -R logs
chown apache:apache -R resource
chown apache:apache -R static
chown apache:apache -R media
chown apache:apache -R celery

message "info:Hexnode MDM Reserve server configuration completed"
message "***********************************************************************************************"

exit 0


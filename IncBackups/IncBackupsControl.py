#!/usr/local/CyberCP/bin/python2
import os
import os.path
import sys

sys.path.append('/usr/local/CyberCP')
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "CyberCP.settings")

import django

try:
    django.setup()
except:
    pass
import threading as multi
from plogical.processUtilities import ProcessUtilities
from IncBackups.models import IncJob, JobSnapshots
from websiteFunctions.models import Websites
import plogical.randomPassword as randomPassword
from plogical.CyberCPLogFileWriter import CyberCPLogFileWriter as logging
from xml.etree.ElementTree import Element, SubElement
from xml.etree import ElementTree
from xml.dom import minidom
from backup.models import DBUsers
import plogical.mysqlUtilities as mysqlUtilities
from plogical.backupUtilities import backupUtilities
from plogical.dnsUtilities import DNS
from mailServer.models import Domains as eDomains
from random import randint
import json
from django.shortcuts import HttpResponse

try:
    from plogical.virtualHostUtilities import virtualHostUtilities
    from plogical.mailUtilities import mailUtilities
except:
    pass


class IncJobs(multi.Thread):

    def __init__(self, function, extraArgs):
        multi.Thread.__init__(self)
        self.function = function
        self.extraArgs = extraArgs
        self.repoPath = ''
        self.passwordFile = ''
        self.statusPath = ''
        self.website = ''
        self.backupDestinations = ''
        self.jobid = 0
        self.metaPath = ''

    def run(self):

        if self.function == 'createBackup':
            self.createBackup()
        elif self.function == 'restorePoint':
            self.restorePoint()
        elif self.function == 'remoteRestore':
            self.restorePoint()

    def getRemoteBackups(self):
        if self.jobid.destination == 'local':
            path = '/home/%s/incbackup' % (self.website)
            command = 'export RESTIC_PASSWORD=%s && restic -r %s snapshots' % (self.passwordFile, path)
            return ProcessUtilities.outputExecutioner(command).split('\n')
        elif self.jobid.destination[:4] == 'sftp':
            path = '/home/backup/%s' % (self.website)
            command = 'export RESTIC_PASSWORD=%s PATH=${PATH}:/usr/bin && restic -r %s:%s snapshots' % (
                self.passwordFile, self.backupDestinations, path)
            return ProcessUtilities.outputExecutioner(command).split('\n')
        else:
            path = '/home/%s/incbackup' % (self.website)
            command = 'export RESTIC_PASSWORD=%s && restic -r %s snapshots' % (self.passwordFile, path)
            return ProcessUtilities.outputExecutioner(command).split('\n')

    def fetchCurrentBackups(self):
        try:
            self.website = self.extraArgs['website']
            self.backupDestinations = self.extraArgs['backupDestinations']
            self.passwordFile = self.extraArgs['password']

            remotePath = '/home/backup/%s' % (self.website)

            command = 'export RESTIC_PASSWORD=%s PATH=${PATH}:/usr/bin && restic -r %s:%s snapshots' % (
            self.passwordFile, self.backupDestinations, remotePath)
            result = ProcessUtilities.outputExecutioner(command).split('\n')

            activator = 0
            json_data = "["
            checker = 0

            for items in result:
                if items.find('---------------') > -1:
                    if activator == 0:
                        activator = 1
                        continue
                    else:
                        activator = 0

                if activator:
                    entry = items.split(' ')
                    logging.writeToFile(str(entry))

                    dic = {'id': entry[0],
                           'date': "%s %s" % (entry[2], entry[3]),
                           'host': entry[5],
                           'path': entry[-1]
                           }

                    if checker == 0:
                        json_data = json_data + json.dumps(dic)
                        checker = 1
                    else:
                        json_data = json_data + ',' + json.dumps(dic)

            json_data = json_data + ']'
            final_json = json.dumps({'status': 1, 'error_message': "None", "data": json_data})
            return HttpResponse(final_json)

        except BaseException, msg:
            logging.writeToFile(str(msg))

    ####

    def getAWSData(self):
        key = self.backupDestinations.split('/')[-1]
        path = '/home/cyberpanel/aws/%s' % (key)
        secret = open(path, 'r').read()
        return key, secret

    def awsFunction(self, fType, backupPath=None, snapshotID=None, bType=None):
        try:
            if fType == 'backup':
                key, secret = self.getAWSData()
                command = 'export AWS_ACCESS_KEY_ID=%s AWS_SECRET_ACCESS_KEY=%s  && restic -r s3:s3.amazonaws.com/%s backup %s --password-file %s' % (
                    key, secret, self.website.domain, backupPath, self.passwordFile)
                result = ProcessUtilities.outputExecutioner(command)
                logging.statusWriter(self.statusPath, result, 1)
                snapShotid = result.split(' ')[-2]
                if bType == 'database':
                    newSnapshot = JobSnapshots(job=self.jobid,
                                               type='%s:%s' % (bType, backupPath.split('/')[-1].strip('.sql')),
                                               snapshotid=snapShotid,
                                               destination=self.backupDestinations)
                else:
                    newSnapshot = JobSnapshots(job=self.jobid, type='%s:%s' % (bType, backupPath),
                                               snapshotid=snapShotid,
                                               destination=self.backupDestinations)
                newSnapshot.save()
            else:
                self.backupDestinations = self.jobid.destination
                key, secret = self.getAWSData()
                command = 'export AWS_ACCESS_KEY_ID=%s AWS_SECRET_ACCESS_KEY=%s  && restic -r s3:s3.amazonaws.com/%s restore %s --password-file %s --target /' % (
                    key, secret, self.website, snapshotID, self.passwordFile)
                result = ProcessUtilities.outputExecutioner(command)
                logging.statusWriter(self.statusPath, result, 1)


        except BaseException, msg:
            logging.statusWriter(self.statusPath, "%s [88][5009]" % (str(msg)), 1)
            return 0

    def localFunction(self, backupPath, type, restore=None):
        if restore == None:
            command = 'restic -r %s backup %s --password-file %s --exclude %s' % (self.repoPath, backupPath, self.passwordFile, self.repoPath)
            result = ProcessUtilities.outputExecutioner(command)
            logging.statusWriter(self.statusPath, result, 1)
            snapShotid = result.split(' ')[-2]

            if type == 'database':
                newSnapshot = JobSnapshots(job=self.jobid,
                                           type='%s:%s' % (type, backupPath.split('/')[-1].strip('.sql')),
                                           snapshotid=snapShotid,
                                           destination=self.backupDestinations)
            else:
                newSnapshot = JobSnapshots(job=self.jobid, type='%s:%s' % (type, backupPath), snapshotid=snapShotid,
                                           destination=self.backupDestinations)
            newSnapshot.save()
        else:
            repoLocation = '/home/%s/incbackup' % (self.website)
            command = 'restic -r %s restore %s --target / --password-file %s' % (
                repoLocation, self.jobid.snapshotid, self.passwordFile)
            result = ProcessUtilities.outputExecutioner(command)
            logging.statusWriter(self.statusPath, result, 1)

    def sftpFunction(self, backupPath, type, restore=None):
        if restore == None:
            remotePath = '/home/backup/%s' % (self.website.domain)
            command = 'export PATH=${PATH}:/usr/bin && restic -r %s:%s backup %s --password-file %s --exclude %s' % (
                self.backupDestinations, remotePath, backupPath, self.passwordFile, self.repoPath)
            result = ProcessUtilities.outputExecutioner(command)
            logging.statusWriter(self.statusPath, result, 1)
            snapShotid = result.split(' ')[-2]

            if type == 'database':
                newSnapshot = JobSnapshots(job=self.jobid,
                                           type='%s:%s' % (type, backupPath.split('/')[-1].strip('.sql')),
                                           snapshotid=snapShotid,
                                           destination=self.backupDestinations)
            else:
                newSnapshot = JobSnapshots(job=self.jobid, type='%s:%s' % (type, backupPath), snapshotid=snapShotid,
                                           destination=self.backupDestinations)
            newSnapshot.save()
        else:
            repoLocation = '/home/backup/%s' % (self.website)
            command = 'export PATH=${PATH}:/usr/bin && restic -r %s:%s restore %s --target / --password-file %s' % (
                self.jobid.destination, repoLocation, self.jobid.snapshotid, self.passwordFile)
            result = ProcessUtilities.outputExecutioner(command)
            logging.statusWriter(self.statusPath, result, 1)

    def restoreData(self):
        try:

            if self.jobid.destination == 'local':
                self.localFunction('none', 'none', 1)
            elif self.jobid.destination[:4] == 'sftp':
                self.sftpFunction('none', 'none', 1)
            else:
                self.awsFunction('restore', '', self.jobid.snapshotid)

        except BaseException, msg:
            logging.statusWriter(self.statusPath, "%s [138][5009]" % (str(msg)), 1)
            return 0

    def restoreDatabase(self):
        try:

            if self.jobid.destination == 'local':
                self.localFunction('none', 'none', 1)
            elif self.jobid.destination[:4] == 'sftp':
                self.sftpFunction('none', 'none', 1)
            else:
                self.awsFunction('restore', '', self.jobid.snapshotid)

            if mysqlUtilities.mysqlUtilities.restoreDatabaseBackup(self.jobid.type.split(':')[1].rstrip('.sql'),
                                                                   '/home/cyberpanel', 'dummy', 'dummy') == 0:
                raise BaseException

            try:
                os.remove('/home/cyberpanel/%s.sql' % (self.jobid.type.split(':')[1]))
            except BaseException, msg:
                logging.writeToFile(str(msg))

        except BaseException, msg:
            logging.statusWriter(self.statusPath, "%s [160][5009]" % (str(msg)), 1)
            return 0

    def restoreEmail(self):
        try:

            if self.jobid.destination == 'local':
                self.localFunction('none', 'none', 1)
            elif self.jobid.destination[:4] == 'sftp':
                self.sftpFunction('none', 'none', 1)
            else:
                self.awsFunction('restore', '', self.jobid.snapshotid)

        except BaseException, msg:
            logging.statusWriter(self.statusPath, "%s [46][5009]" % (str(msg)), 1)
            return 0

    def reconstructWithMeta(self):
        try:

            if self.jobid.destination == 'local':
                self.localFunction('none', 'none', 1)
            elif self.jobid.destination[:4] == 'sftp':
                self.sftpFunction('none', 'none', 1)
            else:
                self.awsFunction('restore', '', self.jobid.snapshotid)

            metaPathNew = '/home/%s/meta.xml' % (self.website)
            execPath = "nice -n 10 /usr/local/CyberCP/bin/python2 " + virtualHostUtilities.cyberPanel + "/IncBackups/restoreMeta.py"
            execPath = execPath + " submitRestore --metaPath %s --statusFile %s" % (metaPathNew, self.statusPath)
            result = ProcessUtilities.outputExecutioner(execPath)
            logging.statusWriter(self.statusPath, result, 1)

        except BaseException, msg:
            logging.statusWriter(self.statusPath, "%s [46][5009]" % (str(msg)), 1)
            return 0

    def restorePoint(self):
        try:
            self.statusPath = self.extraArgs['tempPath']
            self.website = self.extraArgs['website']
            jobid = self.extraArgs['jobid']

            self.jobid = JobSnapshots.objects.get(pk=jobid)

            message = 'Starting restore of %s for %s.' % (self.jobid.snapshotid, self.website)
            logging.statusWriter(self.statusPath, message, 1)
            self.passwordFile = '/home/%s/%s' % (self.website, self.website)

            ##

            if self.jobid.type[:8] == 'database':
                message = 'Restoring database..'
                logging.statusWriter(self.statusPath, message, 1)
                self.restoreDatabase()
                message = 'Database restored.'
                logging.statusWriter(self.statusPath, message, 1)
            elif self.jobid.type[:4] == 'data':
                self.restoreData()
            elif self.jobid.type[:5] == 'email':
                message = 'Restoring email..'
                logging.statusWriter(self.statusPath, message, 1)
                self.restoreEmail()
                message = 'Emails restored.'
                logging.statusWriter(self.statusPath, message, 1)
            elif self.jobid.type[:4] == 'meta':
                message = 'Reconstructing with meta..'
                logging.statusWriter(self.statusPath, message, 1)
                self.reconstructWithMeta()
                message = 'Reconstructed'
                logging.statusWriter(self.statusPath, message, 1)

            logging.statusWriter(self.statusPath, 'Completed', 1)
        except BaseException, msg:
            logging.statusWriter(self.extraArgs['tempPath'], str(msg), 1)

    ### Backup functions

    def prepareBackupMeta(self):
        try:

            ######### Generating meta

            ## XML Generation

            metaFileXML = Element('metaFile')

            child = SubElement(metaFileXML, 'masterDomain')
            child.text = self.website.domain

            child = SubElement(metaFileXML, 'phpSelection')
            child.text = self.website.phpSelection

            child = SubElement(metaFileXML, 'externalApp')
            child.text = self.website.externalApp

            childDomains = self.website.childdomains_set.all()

            databases = self.website.databases_set.all()

            ## Child domains XML

            childDomainsXML = Element('ChildDomains')

            for items in childDomains:
                childDomainXML = Element('domain')

                child = SubElement(childDomainXML, 'domain')
                child.text = items.domain
                child = SubElement(childDomainXML, 'phpSelection')
                child.text = items.phpSelection
                child = SubElement(childDomainXML, 'path')
                child.text = items.path

                childDomainsXML.append(childDomainXML)

            metaFileXML.append(childDomainsXML)

            ## Databases XML

            databasesXML = Element('Databases')

            for items in databases:
                try:
                    dbuser = DBUsers.objects.get(user=items.dbUser)
                    userToTry = items.dbUser
                except:
                    dbusers = DBUsers.objects.all().filter(user=items.dbUser)
                    userToTry = items.dbUser
                    for it in dbusers:
                        dbuser = it
                        break

                    userToTry = mysqlUtilities.mysqlUtilities.fetchuser(items.dbUser)

                    try:
                        dbuser = DBUsers.objects.get(user=userToTry)
                    except:
                        dbusers = DBUsers.objects.all().filter(user=userToTry)
                        for it in dbusers:
                            dbuser = it
                            break

                databaseXML = Element('database')

                child = SubElement(databaseXML, 'dbName')
                child.text = items.dbName
                child = SubElement(databaseXML, 'dbUser')
                child.text = userToTry
                child = SubElement(databaseXML, 'password')
                child.text = dbuser.password

                databasesXML.append(databaseXML)

            metaFileXML.append(databasesXML)

            ## Get Aliases

            aliasesXML = Element('Aliases')

            aliases = backupUtilities.getAliases(self.website.domain)

            for items in aliases:
                child = SubElement(aliasesXML, 'alias')
                child.text = items

            metaFileXML.append(aliasesXML)

            ## Finish Alias

            ## DNS Records XML

            try:

                dnsRecordsXML = Element("dnsrecords")
                dnsRecords = DNS.getDNSRecords(self.website.domain)

                for items in dnsRecords:
                    dnsRecordXML = Element('dnsrecord')

                    child = SubElement(dnsRecordXML, 'type')
                    child.text = items.type
                    child = SubElement(dnsRecordXML, 'name')
                    child.text = items.name
                    child = SubElement(dnsRecordXML, 'content')
                    child.text = items.content
                    child = SubElement(dnsRecordXML, 'priority')
                    child.text = str(items.prio)

                    dnsRecordsXML.append(dnsRecordXML)

                metaFileXML.append(dnsRecordsXML)

            except BaseException, msg:
                logging.statusWriter(self.statusPath, '%s. [158:prepMeta]' % (str(msg)), 1)

            ## Email accounts XML

            try:
                emailRecordsXML = Element('emails')
                eDomain = eDomains.objects.get(domain=self.website.domain)
                emailAccounts = eDomain.eusers_set.all()

                for items in emailAccounts:
                    emailRecordXML = Element('emailAccount')

                    child = SubElement(emailRecordXML, 'email')
                    child.text = items.email
                    child = SubElement(emailRecordXML, 'password')
                    child.text = items.password

                    emailRecordsXML.append(emailRecordXML)

                metaFileXML.append(emailRecordsXML)
            except BaseException, msg:
                logging.statusWriter(self.statusPath, '%s. [warning:179:prepMeta]' % (str(msg)), 1)

            ## Email meta generated!

            def prettify(elem):
                """Return a pretty-printed XML string for the Element.
                """
                rough_string = ElementTree.tostring(elem, 'utf-8')
                reparsed = minidom.parseString(rough_string)
                return reparsed.toprettyxml(indent="  ")

            ## /home/example.com/backup/backup-example-06-50-03-Thu-Feb-2018/meta.xml -- metaPath

            metaPath = '/home/cyberpanel/%s' % (str(randint(1000, 9999)))

            xmlpretty = prettify(metaFileXML).encode('ascii', 'ignore')
            metaFile = open(metaPath, 'w')
            metaFile.write(xmlpretty)
            metaFile.close()
            os.chmod(metaPath, 0640)

            ## meta generated

            logging.statusWriter(self.statusPath, 'Meta data is ready..', 1)

            metaPathNew = '/home/%s/meta.xml' % (self.website.domain)
            command = 'mv %s %s' % (metaPath, metaPathNew)
            ProcessUtilities.executioner(command)

            return 1

        except BaseException, msg:
            logging.statusWriter(self.statusPath, "%s [207][5009]" % (str(msg)), 1)
            return 0

    def backupData(self):
        try:
            logging.statusWriter(self.statusPath, 'Backing up data..', 1)
            backupPath = '/home/%s' % (self.website.domain)

            if self.backupDestinations == 'local':
                self.localFunction(backupPath, 'data')
            elif self.backupDestinations[:4] == 'sftp':
                self.sftpFunction(backupPath, 'data')
            else:
                self.awsFunction('backup', backupPath, '', 'data')

            logging.statusWriter(self.statusPath,
                                 'Data for %s backed to %s.' % (self.website.domain, self.backupDestinations), 1)
            return 1
        except BaseException, msg:
            logging.statusWriter(self.statusPath, '%s. [IncJobs.backupData.223][5009]' % str(msg), 1)
            return 0

    def backupDatabases(self):
        try:
            logging.statusWriter(self.statusPath, 'Backing up databases..', 1)

            databases = self.website.databases_set.all()

            for items in databases:
                if mysqlUtilities.mysqlUtilities.createDatabaseBackup(items.dbName, '/home/cyberpanel') == 0:
                    return 0

                dbPath = '/home/cyberpanel/%s.sql' % (items.dbName)

                if self.backupDestinations == 'local':
                    self.localFunction(dbPath, 'database')
                elif self.backupDestinations[:4] == 'sftp':
                    self.sftpFunction(dbPath, 'database')
                else:
                    self.awsFunction('backup', dbPath, '', 'database')

                try:
                    os.remove('/home/cyberpanel/%s.sql' % (items.dbName))
                except BaseException, msg:
                    logging.statusWriter(self.statusPath,
                                         'Failed to delete database: %s. [IncJobs.backupDatabases.456]' % str(msg), 1)
            return 1
        except BaseException, msg:
            logging.statusWriter(self.statusPath, '%s. [IncJobs.backupDatabases.269][5009]' % str(msg), 1)
            return 0

    def emailBackup(self):
        try:
            logging.statusWriter(self.statusPath, 'Backing up emails..', 1)

            backupPath = '/home/vmail/%s' % (self.website.domain)

            if self.backupDestinations == 'local':
                self.localFunction(backupPath, 'email')
            elif self.backupDestinations[:4] == 'sftp':
                self.sftpFunction(backupPath, 'email')
            else:
                self.awsFunction('backup', backupPath, '', 'email')

            logging.statusWriter(self.statusPath,
                                 'Emails for %s backed to %s.' % (self.website.domain, self.backupDestinations), 1)
            return 1
        except BaseException, msg:
            logging.statusWriter(self.statusPath, '%s. [IncJobs.emailBackup.269][5009]' % str(msg), 1)
            return 0

    def metaBackup(self):
        try:
            logging.statusWriter(self.statusPath, 'Backing up meta..', 1)

            backupPath = '/home/%s/meta.xml' % (self.website.domain)

            if self.backupDestinations == 'local':
                self.localFunction(backupPath, 'meta')
            elif self.backupDestinations[:4] == 'sftp':
                self.sftpFunction(backupPath, 'meta')
            else:
                self.awsFunction('backup', backupPath, '', 'meta')

            logging.statusWriter(self.statusPath,
                                 'Meta for %s backed to %s.' % (self.website.domain, self.backupDestinations), 1)
            return 1
        except BaseException, msg:
            logging.statusWriter(self.statusPath, '%s. [IncJobs.metaBackup.269][5009]' % str(msg), 1)
            return 0

    def initiateRepo(self):
        try:
            logging.statusWriter(self.statusPath, 'Will first initiate backup repo..', 1)

            if self.backupDestinations == 'local':
                command = 'restic init --repo %s --password-file %s' % (self.repoPath, self.passwordFile)
                result = ProcessUtilities.outputExecutioner(command)
                logging.statusWriter(self.statusPath, result, 1)

            elif self.backupDestinations[:4] == 'sftp':
                remotePath = '/home/backup/%s' % (self.website.domain)
                command = 'export PATH=${PATH}:/usr/bin && restic init --repo %s:%s --password-file %s' % (
                self.backupDestinations, remotePath, self.passwordFile)
                result = ProcessUtilities.outputExecutioner(command)
                logging.statusWriter(self.statusPath, result, 1)
            else:
                key, secret = self.getAWSData()
                command = 'export AWS_ACCESS_KEY_ID=%s AWS_SECRET_ACCESS_KEY=%s  && restic -r s3:s3.amazonaws.com/%s init --password-file %s' % (
                key, secret, self.website.domain, self.passwordFile)
                result = ProcessUtilities.outputExecutioner(command)
                logging.statusWriter(self.statusPath, result, 1)
                return 1

            logging.statusWriter(self.statusPath,
                                 'Repo %s initiated for %s.' % (self.backupDestinations, self.website.domain), 1)
            return 1
        except BaseException, msg:
            logging.statusWriter(self.statusPath, '%s. [IncJobs.initiateRepo.47][5009]' % str(msg), 1)
            return 0

    def createBackup(self):
        self.statusPath = self.extraArgs['tempPath']
        website = self.extraArgs['website']
        self.backupDestinations = self.extraArgs['backupDestinations']
        websiteData = self.extraArgs['websiteData']
        websiteEmails = self.extraArgs['websiteEmails']
        websiteSSLs = self.extraArgs['websiteSSLs']
        websiteDatabases = self.extraArgs['websiteDatabases']

        self.website = Websites.objects.get(domain=website)

        newJob = IncJob(website=self.website)
        newJob.save()

        self.jobid = newJob

        self.passwordFile = '/home/%s/%s' % (self.website.domain, self.website.domain)

        self.repoPath = '/home/%s/incbackup' % (self.website.domain)

        if not os.path.exists(self.passwordFile):
            password = randomPassword.generate_pass()
            command = 'echo "%s" > %s' % (password, self.passwordFile)
            ProcessUtilities.executioner(command, self.website.externalApp)

            command = 'chmod 600 %s' % (self.passwordFile)
            ProcessUtilities.executioner(command)

        if self.initiateRepo() == 0:
            return

        if self.prepareBackupMeta() == 0:
            return

        if websiteData:
            if self.backupData() == 0:
                return

        if websiteDatabases:
            if self.backupDatabases() == 0:
                return

        if websiteEmails:
            if self.emailBackup() == 0:
                return

        self.metaBackup()

        metaPathNew = '/home/%s/meta.xml' % (self.website.domain)

        try:
            command = 'rm -f %s' % (metaPathNew)
            ProcessUtilities.executioner(command)
        except BaseException, msg:
            logging.statusWriter(self.statusPath,
                                 'Failed to delete meta file: %s. [IncJobs.createBackup.591]' % str(msg), 1)

        logging.statusWriter(self.statusPath, 'Completed', 1)

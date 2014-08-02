# -*- coding: UTF-8 -*-
#-----------------------------------------------------------------------------
# project     : Lisa client
# module      : client
# file        : config_manager.py
# description : Manage client configuration
# author      : G.Dumee
#-----------------------------------------------------------------------------
# copyright   : Neotique
#-----------------------------------------------------------------------------


#-----------------------------------------------------------------------------
# Imports
#-----------------------------------------------------------------------------
from twisted.python import log
import os
import pkg_resources
import json
import platform
from lisa.Neotique.NeoTrans import NeoTrans


#-----------------------------------------------------------------------------
# ConfigManager
#-----------------------------------------------------------------------------
class ConfigManager(object):
    """
    Manage configuration
    """
    # Singleton
    __instance = None

    #-----------------------------------------------------------------------------
    def __init__(self, config_file = ""):
        self.valid_flag = True
        self.configuration = {}

        # Read configuration file
        if os.path.isfile(config_file) == True and config_file.endswith('.json') == True:
            self.configuration = json.load(open(config_file))
        elif os.path.isfile('/etc/lisa/client/configuration/lisa.json') == True:
            self.configuration = json.load(open('/etc/lisa/client/configuration/lisa.json'))
        else:
            self.configuration = json.load(open(pkg_resources.resource_filename(__name__, 'configuration/lisa.json.sample')))

        # Path
        self.configuration['path'] = os.path.dirname(__file__)

        # KWS params
        if self.configuration.has_key("keyword_score") == False:
            self.configuration['keyword_score'] = -10000
        if self.configuration.has_key('asr') == False:
            self.configuration['asr'] = "wit"
        if self.configuration.has_key('confidence') == False:
            self.configuration['wit_confidence'] = 0.5

        # Lang params
        if self.configuration.has_key('lang') == False:
            self.configuration['lang'] = "fr-FR"
        self.configuration['lang_short'] = self.configuration['lang'].split('-')[0]

        # TTS params
        if self.configuration.has_key("tts") == False:
            self.configuration['tts'] = "pico"
            self.configuration['tts_ext'] = "wav"
        elif self.configuration['tts'].lower() == "pico" or self.configuration["tts"].lower() == "picotts":
            self.configuration['tts'] = "pico"
            self.configuration['tts_ext'] = "wav"
        elif self.configuration['tts'].lower() == "voicerss" and self.configuration.has_key('voicerss_key'):
            self.configuration['tts'] = "voicerss"
            self.configuration['tts_ext'] = "ogg"
        else:
            self.configuration['tts'] = "pico"
            self.configuration['tts_ext'] = "wav"
        if self.configuration.has_key('enable_secure_mode') == False:
            self.configuration['enable_secure_mode'] = False

        # Client params
        self.configuration['client_name'] = platform.node()
        if self.configuration.has_key("zone") == False:
            self.configuration['zone'] = ""

        # URL and port
        if self.configuration.has_key('lisa_url') == False:
            log.err("Error configuration : no server URL : lisa_url")
            self.valid_flag = False
        if self.configuration.has_key('lisa_port') == False:
            log.err("Error configuration : no server port : 'lisa_port'")
            self.valid_flag = False

        # SSL
        if self.configuration.has_key('enable_secure_mode') == True and self.configuration['enable_secure_mode'] == True:
            # SSL cert
            if self.configuration.has_key('lisa_engine_ssl_crt') == True:
                if os.path.isfile(self.configuration['lisa_engine_ssl_crt']) == False:
                    log.err("Error configuration : SSL certificat {} is not found : 'lisa_engine_ssl_crt'".format(self.configuration['lisa_engine_ssl_crt']))
                    self.valid_flag = False
            elif os.path.isfile(self.configuration['path'] + '/configuration/ssl/client.crt') == False:
                log.err("Error configuration : no valid SSL certificat found : 'lisa_engine_ssl_crt'")
                self.valid_flag = False
            else:
                self.configuration['lisa_engine_ssl_crt'] = os.path.normpath(self.configuration['path'] + '/configuration/ssl/client.crt')

            # SSL private key
            if self.configuration.has_key('lisa_engine_ssl_key') == True:
                if os.path.isfile(self.configuration['lisa_engine_ssl_key']) == False:
                    log.err("Error configuration : SSL private key {} is not found : 'lisa_engine_ssl_key'".format(self.configuration['lisa_engine_ssl_key']))
                    self.valid_flag = False
            elif os.path.isfile(self.configuration['path'] + '/configuration/ssl/client.key') == False:
                log.err("Error configuration : no valid SSL private key found : 'lisa_engine_ssl_key'")
                self.valid_flag = False
            else:
                self.configuration['lisa_engine_ssl_key'] = os.path.normpath(self.configuration['path'] + '/configuration/ssl/client.key')

        # Translation function
        lang_path = self.configuration['path'] + "/lang"
        self.configuration['trans'] = NeoTrans(domain = 'lisa', localedir = lang_path, languages = [self.configuration['lang_short']]).Trans

    #-----------------------------------------------------------------------------
    @classmethod
    def getConfiguration(cls):
        if cls.__instance is None:
            cls.__instance = ConfigManager()
        return cls.__instance.configuration

    #-----------------------------------------------------------------------------
    @classmethod
    def setConfiguration(cls, config_file):
        cls.__instance = None
        cls.__instance = ConfigManager(config_file)
        return cls.__instance.valid_flag


# --------------------- End of config_manager.py  ---------------------

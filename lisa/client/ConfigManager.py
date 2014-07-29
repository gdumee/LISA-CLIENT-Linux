# -*- coding: UTF-8 -*-
#-----------------------------------------------------------------------------
# project     : Lisa client
# module      : server
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
    """
    # Singleton
    __instance = None

    #-----------------------------------------------------------------------------
    def __init__(self, config_file = ""):
        self.configuration = {}
        if os.path.exists(config_file) == True and config_file.endswith('.json') == True:
            self.configuration = json.load(open(config_file))
        elif os.path.exists('/etc/lisa/client/lisa.json') == True:
            self.configuration = json.load(open('/etc/lisa/client/lisa.json'))
        else:
            self.configuration = json.load(open(pkg_resources.resource_filename(__name__, 'configuration/lisa.json.sample')))

        self.configuration['path'] = os.path.dirname(__file__)

        if self.configuration.has_key("keyword_score") == False:
            self.configuration['keyword_score'] = -10000
        if self.configuration.has_key('asr') == False:
            self.configuration['asr'] = "wit"

        if self.configuration.has_key('lang') == False:
            self.configuration['lang'] = "fr-FR"
        self.configuration['lang_short'] = self.configuration['lang'].split('-')[0]
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
        self.configuration['client_name'] = platform.node()
        if self.configuration.has_key("zone") == False:
            self.configuration['zone'] = ""
        if self.configuration.has_key('confidence') == False:
            self.configuration['wit_confidence'] = 0.5
        if self.configuration.has_key('asr') == False:
            self.configuration['asr'] = "wit"

        # Check vital configuration
        if self.configuration.has_key('lisa_url') == False or self.configuration.has_key('lisa_engine_port_ssl') == False:
            self.valid_flag = False

        # Translation function
        lang_path = self.configuration['path'] + "/lang"
        self.configuration['trans'] = NeoTrans(domain = 'lisa', localedir = lang_path, languages = [self.configuration['lang_short']]).Trans

        self.valid_flag = True

    #-----------------------------------------------------------------------------
    def _getConfiguration(self):
        if ConfigManager.__instance is None:
            ConfigManager.__instance = ConfigManager()
            log.msg("ConfigManager initialized")
        return ConfigManager.__instance.configuration
    getConfiguration = classmethod(_getConfiguration)

    #-----------------------------------------------------------------------------
    def _setConfiguration(self, config_file):
        ConfigManager.__instance = None
        ConfigManager.__instance = ConfigManager(config_file)
        return ConfigManager.__instance.valid_flag
    setConfiguration = classmethod(_setConfiguration)


# --------------------- End of config_manager.py  ---------------------

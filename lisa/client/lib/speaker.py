# -*- coding: UTF-8 -*-
#-----------------------------------------------------------------------------
# project     : Lisa client
# module      : lib
# file        : speaker.py
# description : TTS generation
# author      : G.Dumee
#-----------------------------------------------------------------------------
# copyright   : Neotique
#-----------------------------------------------------------------------------


#-----------------------------------------------------------------------------
# Imports
#-----------------------------------------------------------------------------
from lisa.client.ConfigManager import ConfigManagerSingleton
from lisa.Neotique.NeoTrans import NeoTrans
import threading
import os
import gettext
from lisa.client.lib.player import Player
from Queue import Queue
from time import sleep
from subprocess import call
import urllib
from urllib import urlencode, urlopen
from random import randint
from twisted.python import log


#-----------------------------------------------------------------------------
# Globals
#-----------------------------------------------------------------------------
soundfile = 'tts-output'
soundpath = '/tmp/'

configuration = ConfigManagerSingleton.get().getConfiguration()
path = '/'.join([ConfigManagerSingleton.get().getPath(), 'lang'])


#-----------------------------------------------------------------------------
# Speaker
#-----------------------------------------------------------------------------
class Speaker(threading.Thread):
    """
    Speaker class is a singleton managing TTS for the client
    """
    # Singleton instance
    __instance = None

    # TTS engine enum
    _engines = type('Enum', (), dict({"pico": 1, "voicerss": 2}))

    #-----------------------------------------------------------------------------
    def __init__(self):
        if self.__instance is not None:
            raise Exception("Singleton can't be created twice !")

        # Init thread class
        threading.Thread.__init__(self)
        self._stopevent = threading.Event()
        self.configuration = ConfigManagerSingleton.get().getConfiguration()

        self.queue = Queue([])
        self.lang = "en-EN"
        if self.configuration.has_key('lang'):
            self.lang = self.configuration['lang']
        if self.configuration.has_key("tts") == False or self.configuration["tts"].lower() == "pico" or self.configuration["tts"].lower() == "picotts":
            self.engine = "pico"
            self.ext = "wav"
        elif self.configuration["tts"].lower() == "voicerss" and "voicerss_key" in self.configuration:
            self.engine = "voicerss"
            self.ext = "ogg"
            self.voicerss_key = self.configuration["voicerss_key"]
        else:
            Player.play_block("error_conf")
            return
        
        # Translation function
        self._ = translation = gettext.translation(domain = 'lisa', localedir = path, fallback = True, languages = [self.lang.split('-')[0]]).ugettext
        self._ = NeoTrans(self._, path).Trans

        # Start thread
        threading.Thread.start(self)

    #-----------------------------------------------------------------------------
    def _start(self):
        # Create singleton
        if self.__instance is None:
            self.__instance = Speaker()
    start = classmethod(_start)

    #-----------------------------------------------------------------------------
    def _speak(self, msg, block = True):
        # Queue message
        if self.__instance is not None:
            self.__instance.queue.put(msg)

            # Waits the end
            if block == True:
                self.__instance.queue.join()
    speak = classmethod(_speak)

    #-----------------------------------------------------------------------------
    def _stop(self):
        # Raise stop event
        if self.__instance is not None:
            self.__instance._stopevent.set()
            self.__instance = None

        # Free player
        Player.free()
    stop = classmethod(_stop)

    #-----------------------------------------------------------------------------
    def run(self):
        """
        Recorder main loop
        """
        # Thread loop
        while not self._stopevent.isSet():
            # Wait queue
            if self.queue.empty():
                sleep(.1)
                continue

            # Get translated message
            data = self._(self.queue.get())
            filename = "{path}{file}.{ext}".format(path = soundpath, file = soundfile, ext = self.ext)

            # Pico TTS
            if self.engine == "pico":
                call(['/usr/bin/pico2wave', '-w', filename, '-l', self.lang, '"' + data.encode('utf8') + '"'])

            # VoiceRSS
            elif self.engine == "voicerss":
                urllib.urlretrieve("http://api.voicerss.org/?%s".format(urlencode({ "c": self.ext.upper(),
                                                                                    "r": 1,
                                                                                    "f": "16khz_16bit_mono",
                                                                                    "key": self.voicerss_key,
                                                                                    "src": data,
                                                                                    "hl": self.lang}), filename))

            # Play synthetized file
            if os.path.exists(filename):
                log.msg(self._("playing_TTS"))
                Player.play_block(sound = filename, path = soundpath, ext = self.ext)
            else:
                log.msg(self._("error_generate_TTS").format(filename = filename))

            # Remove message from queue
            self.queue.task_done()

# --------------------- End of speaker.py  ---------------------

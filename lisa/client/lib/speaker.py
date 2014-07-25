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
from lisa.client.ConfigManager import ConfigManager
import threading
import os
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
    def __init__(self, listener):
        if self.__instance is not None:
            raise Exception("Singleton can't be created twice !")

        # Init thread class
        threading.Thread.__init__(self)
        self._stopevent = threading.Event()
        self.configuration = ConfigManager.getConfiguration()
        self.queue = Queue([])
        self.listener = listener

        # Start thread
        threading.Thread.start(self)

    #-----------------------------------------------------------------------------
    def _start(self, listener):
        # Create singleton
        if self.__instance is None:
            self.__instance = Speaker(listener)
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
            data = self.queue.get().encode('utf-8')
            filename = "{path}{file}.{ext}".format(path = soundpath, file = soundfile, ext = self.configuration['tts_ext'])

            # Pico TTS
            if self.configuration["tts"] == "pico":
                call(['/usr/bin/pico2wave', '-w', filename, '-l', self.configuration['lang'], '"' + data + '"'])

            # VoiceRSS
            elif self.configuration["tts"] == "voicerss":
                urllib.urlretrieve("http://api.voicerss.org/?%s".format(urlencode({ "c": self.configuration['tts_ext'].upper(),
                                                                                    "r": 1,
                                                                                    "f": "16khz_16bit_mono",
                                                                                    "key": self.configuration["voicerss_key"],
                                                                                    "src": data,
                                                                                    "hl": self.configuration['lang']}), filename))

            # Play synthetized file
            if os.path.exists(filename):
                log.msg("Playing generated TTS")
                self.listener.setRunningState(False)
                Player.playBlock(sound = filename, path = soundpath, ext = self.configuration['tts_ext'])
                self.listener.setRunningState(True)
            else:
                log.msg("Error while generating TTS file : {filename}".format(filename = filename))

            # Remove message from queue
            self.queue.task_done()

# --------------------- End of speaker.py  ---------------------

# -*- coding: UTF-8 -*-
#-----------------------------------------------------------------------------
# project     : Lisa client
# module      : lib
# file        : player.py
# description : Play sounds from a file
# author      : G.Dumee
#-----------------------------------------------------------------------------
# copyright   : Neotique
#-----------------------------------------------------------------------------


#-----------------------------------------------------------------------------
# Imports
#-----------------------------------------------------------------------------
import gst
import os
import gobject
from lisa.client.ConfigManager import ConfigManager
gobject.threads_init()


#-----------------------------------------------------------------------------
# Globals
#-----------------------------------------------------------------------------
configuration = ConfigManager.getConfiguration()


#-----------------------------------------------------------------------------
# Player
#-----------------------------------------------------------------------------
class Player:
    """
    Play a sound file. Determine path and extension if not provided.
    """
    # Singleton instance
    __instance = None

    #-----------------------------------------------------------------------------
    def play(self, sound, path = None, ext = None):
        # Create singleton
        if self.__instance is None:
            self.__instance = Player()

        # Call singleton API
        self.__instance._play(sound, path, ext)
    play = classmethod(play)

    #-----------------------------------------------------------------------------
    def playBlock(self, sound, path = None, ext = None):
        # Create singleton
        if self.__instance is None:
            self.__instance = Player()

        # Call singleton API
        self.__instance._playBlock(sound, path, ext)
    playBlock = classmethod(playBlock)

    #-----------------------------------------------------------------------------
    def free(self):
        # Create singleton
        if self.__instance is None:
            return

        # Call singleton API
        self.__instance._free()
    free = classmethod(free)

    #-----------------------------------------------------------------------------
    def __init__(self):
        # Check Singleton
        if self.__instance is not None:
            raise Exception("Singleton can't be created twice !")

        # Create a gtreamer playerbin
        self._pipeline = None

        # Connect End Of Stream handler on bus
        self.main_loop = gobject.MainLoop()

    #-----------------------------------------------------------------------------
    def _eosHandler(self, bus, message):
        self._pipeline.set_state(gst.STATE_READY)
        self.main_loop.quit()

    #-----------------------------------------------------------------------------
    def _play(self, sound, path=None, ext=None):
        # Create player once
        if self._pipeline is None:
            self._pipeline = gst.element_factory_make("playbin2", "player")

            # Connect End Of Stream handler on bus
            bus = self._pipeline.get_bus()
            bus.add_signal_watch()
            bus.connect('message::eos', self._eosHandler)

        # Stop previous play if any
        else:
            self._pipeline.set_state(gst.STATE_READY)

        # Get path
        if not path:
            path = "{0}/sounds".format(configuration['path'])

        # Search extension
        if os.path.isfile(sound):
            filename = sound
        elif ext is not None and os.path.isfile("{path}/{file}.{ext}".format(path = path, file = sound, ext = ext)):
            filename = "{path}/{file}.{ext}".format(path = path, file = sound, ext = ext)
        elif os.path.isfile("{path}/{file}.{ext}".format(path = path, file = sound, ext = "wav")):
            filename = "{path}/{file}.{ext}".format(path = path, file = sound, ext = "wav")
        elif os.path.isfile("{path}/{file}.{ext}".format(path = path, file = sound, ext = "ogg")):
            filename = "{path}/{file}.{ext}".format(path = path, file = sound, ext = "ogg")
        elif os.path.isfile("{path}/{file}.{ext}".format(path = "/tmp", file = sound, ext = "wav")):
            filename = "{path}/{file}.{ext}".format(path = "/tmp", file = sound, ext = "wav")
        elif os.path.isfile("{path}/{file}.{ext}".format(path = "/tmp", file = sound, ext = "ogg")):
            filename = "{path}/{file}.{ext}".format(path = "/tmp", file = sound, ext = "ogg")
        else:
            filename = '{path}/sounds/pi-cancel.wav'.format(path = configuration['path'])

        # Play file
        self._pipeline.set_property('uri', 'file://{file}'.format(file = filename))
        self._pipeline.set_state(gst.STATE_PLAYING)


    #-----------------------------------------------------------------------------
    def _playBlock(self, sound, path=None, ext=None):
        """
        Play sound but block until end
        """
        # Play sound
        Player.play(sound = sound, path = path, ext = ext)

        # Wait for EOS signal in mail loop
        self.main_loop.run()


    #-----------------------------------------------------------------------------
    def _free(self):
        """
        Free player
        """
        # Delete player
        if self._pipeline is not None:
            self._pipeline.set_state(gst.STATE_NULL)
            self._pipeline = None

# --------------------- End of player.py  ---------------------

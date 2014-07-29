# -*- coding: UTF-8 -*-
#-----------------------------------------------------------------------------
# project     : Lisa client
# module      : lib
# file        : listener.py
# description : Continuous Keyword detector
# author      : G.Dumee
#-----------------------------------------------------------------------------
# copyright   : Neotique
#-----------------------------------------------------------------------------


#-----------------------------------------------------------------------------
# Imports
#-----------------------------------------------------------------------------
import pygst
pygst.require('0.10')
import gobject
gobject.threads_init()
from dbus.mainloop.glib import DBusGMainLoop
DBusGMainLoop(set_as_default=True)
import gst, os, string
from time import sleep,time
import threading
try: # It fixes a bug with the pocketpshinx import. The first time it fails, but the second import is ok.
    import pocketsphinx
except:
    pass
import pocketsphinx
from twisted.python import log
from lisa.client.lib.speaker import Speaker
from lisa.client.lib.recorder import Recorder
from lisa.client.ConfigManager import ConfigManager


#-----------------------------------------------------------------------------
# Globals
#-----------------------------------------------------------------------------
# Global configuration
NUM_PIPES = 2
VADER_MAX_LENGTH = 1


#-----------------------------------------------------------------------------
# Listener
#-----------------------------------------------------------------------------
class Listener(threading.Thread):
    """
    The goal is to listen for a keyword, then it starts a voice recording
    """

    #-----------------------------------------------------------------------------
    def __init__(self, factory):
        # Init thread class
        threading.Thread.__init__(self)
        self._stopevent = threading.Event()

        self.configuration = ConfigManager.getConfiguration()
        self._ = self.configuration['trans']
        self.factory = factory
        self.botname = ""
        self.scores = []
        self.recorder = Recorder(factory = factory)
        self.running_state = False

        # Find client path
        if os.path.isdir('/var/lib/lisa/client/pocketsphinx'):
            self.client_path = '/var/lib/lisa/client/pocketsphinx'
        else:
            self.client_path = "{0}/lib/pocketsphinx".format(self.configuration['path'])

        # Initialize with a default bot name
        self.setBotName("neo")

        # Start thread
        threading.Thread.start(self)

    #-----------------------------------------------------------------------------
    def setBotName(self, botname):
        # If nothing to do
        if botname == self.botname:
            return
        self.botname = botname

        # Pause thread
        self.setRunningState(state = False)

        # Init pipes
        self.pipes = []
        for i in range(NUM_PIPES):
            self.pipes.append({'vad' : None, 'ps' : None, 'timeout' : 0})

        # Build Gstreamer pipeline
        if self.configuration['asr'] == "ispeech":
            enc_str = 'speexenc mode=2'
        elif self.configuration['asr'] == "google":
            enc_str = 'flacenc'
        # Default Wit
        else:
            enc_str = 'lamemp3enc bitrate=16 mono=true'
        pipeline = 'pulsesrc' \
                    + ' ! tee name=audio_tee' \
                    + ' audio_tee.' \
                    + ' ! queue ! audiodynamic characteristics=soft-knee mode=compressor threshold=0.5 ratio=0.5 ! audioconvert ! audioresample' \
                    + ' ! audio/x-raw-int, format=(string)S16_LE, channels=1, rate=16000' \
                    + ' ! ' + enc_str \
                    + ' ! appsink name=rec_sink emit-signals=true async=false' \
                    + ' audio_tee.' \
                    + ' ! queue ! audiocheblimit mode=1 cutoff=150' \
                    + ' ! audiodynamic ! audioconvert ! audioresample' \
                    + ' ! tee name=asr_tee'

        # Add pocketsphinx
        for i in range(NUM_PIPES):
            pipeline = pipeline \
                    + ' asr_tee.' \
                    + ' ! vader name=vad_{0} auto-threshold=true'.format(i) \
                    + ' ! pocketsphinx name=asr_{0}'.format(i) \
                    + ' ! fakesink async=false'

        # Create pipeline
        self.pipeline = gst.parse_launch(pipeline)

        # Configure pipes
        for i in range(NUM_PIPES):
            # Initialize vader
            vader = self.pipeline.get_by_name('vad_{0}'.format(i))
            vader.connect('vader-start', self._vaderStart, i)
            vader.connect('vader-stop', self._vaderStop, i)
            self.pipes[i]['vad'] = vader

            # Initialize pocketsphinx
            asr = self.pipeline.get_by_name('asr_{0}'.format(i))
            asr.set_property("dict", "{path}/{bot}.dic".format(path = self.client_path, bot = self.botname))
            asr.set_property("lm", "{path}/{bot}.lm".format(path = self.client_path, bot = self.botname))
            if self.configuration.has_key("hmm"):
                if os.path.isdir(self.configuration["hmm"]):
                    asr.set_property("hmm", self.configuration["hmm"])
                else:
                    hmm_path = "{path}/{hmm}".format(path = self.client_path, hmm = self.configuration["hmm"])
                    if os.path.isdir(hmm_path):
                        asr.set_property("hmm", hmm_path)
            asr.connect('result', self._asrResult, i)
            asr.set_property('configured', 1)
            self.pipes[i]['ps'] = pocketsphinx.Decoder(boxed = asr.get_property('decoder'))

        # Start pipeline
        self.pipeline.set_state(gst.STATE_PLAYING)

        # Restart
        self.setRunningState(state = True)

    #-----------------------------------------------------------------------------
    def setRunningState(self, state):
        if state == True:
            # Restart
            self.running_state = True
            self.recorder.setRunningState(state = True, rec_sink = self.pipeline.get_by_name('rec_sink'))
        else:
            # Pause thread
            self.running_state = False
            self.recorder.setRunningState(state = False)

    #-----------------------------------------------------------------------------
    def setContinuousMode(self, enabled, wit_context = None):
        # Change continuous mode in recorder
        self.recorder.setContinuousMode(enabled = enabled, wit_context = wit_context)

    #-----------------------------------------------------------------------------
    def run(self):
        """
        Listener main loop
        """
        # Thread loop
        while not self._stopevent.isSet():
            if self.running_state == True:
                for p in self.pipes:
                    if p['timeout'] > 0 and time() >= p['timeout']:
                        # Force silent to cut current utterance
                        p['vad'].set_property('silent', True)
                        p['vad'].set_property('silent', False)

                        # Manual start (vader_start may be not called after the forced silence)
                        p['timeout'] += VADER_MAX_LENGTH
                        self.recorder.vaderStart()
            sleep(.1)

        # Stop pipeline
        self.pipeline.set_state(gst.STATE_NULL)
        self.pipeline = None

    #-----------------------------------------------------------------------------
    def stop(self):
        """
        Stop listener.
        """
        # Stop everything
        self.recorder.stop()
        self._stopevent.set()

    #-----------------------------------------------------------------------------
    def _vaderStart(self, ob, message, pipe_id):
        """
        Vader start detection
        """
        # Vader start
        if self.pipes[pipe_id]['timeout'] == 0:
            self.pipes[pipe_id]['timeout'] = time() + VADER_MAX_LENGTH * (1 + pipe_id / 2.0)
        self.recorder.vaderStart()

    #-----------------------------------------------------------------------------
    def _vaderStop(self, ob, message, pipe_id):
        """
        Vader stop detection
        """
        # Vader stop
        self.pipes[pipe_id]['timeout'] = 0
        self.recorder.vaderStop()

    #-----------------------------------------------------------------------------
    def _asrResult(self, asr, text, uttid, pipe_id):
        """
        Result from pocketsphinx : checking keyword recognition
        """
        # When not running
        if self.running_state == False:
            return

        # Get score from decoder
        dec_text, dec_uttid, dec_score = self.pipes[pipe_id]['ps'].get_hyp()

        # Detection must have a minimal score to be valid
        if dec_score != 0 and dec_score < self.configuration['keyword_score']:
            log.msg("I recognized the {word} keyword but I think it's a false positive according the {score} score".format(word = self.botname, score = dec_score))
            return

        # Activate recorder
        self.recorder.activate()

        # Logs
        self.scores.append(dec_score)
        log.msg("======================")
        log.msg("{word} keyword detected".format(word = self.botname))
        log.msg("score: {score} (min {min}, moy {moy}, max {max})".format(score = dec_score, min = min(self.scores), moy = sum(self.scores) / len(self.scores), max = max(self.scores)))

# --------------------- End of listener.py  ---------------------

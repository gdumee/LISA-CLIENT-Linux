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
from lisa.client.ConfigManager import ConfigManagerSingleton


#-----------------------------------------------------------------------------
# Globals
#-----------------------------------------------------------------------------
# Current path
PWD = os.path.dirname(os.path.abspath(__file__))

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

    def __init__(self, lisa_client):
        # Init thread class
        threading.Thread.__init__(self)
        self._stopevent = threading.Event()

        configuration = ConfigManagerSingleton.get().getConfiguration()
        self.botname = lisa_client.botname.lower()
        self.scores = []
        self.pipes = []
        self.recorder = None
        for i in range(NUM_PIPES):
            self.pipes.append({'vad' : None, 'ps' : None, 'start' : 0})
        self.keyword_score = -10000
        if configuration.has_key("keyword_score"):
            self.keyword_score = configuration['keyword_score']
        self.asr_engine = "wit"
        if configuration.has_key('asr'):
            self.asr_engine = configuration['asr']

        # Find client path
        if os.path.isdir('/var/lib/lisa/client/pocketsphinx'):
            client_path = '/var/lib/lisa/client/pocketsphinx'
        else:
            client_path = "{0}/pocketsphinx".format(PWD)

        # Build Gstreamer pipeline
        if self.asr_engine == "ispeech":
            enc_str = 'speexenc mode=2'
        elif self.asr_engine == "google":
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
            vader.connect('vader-start', self._vader_start, i)
            vader.connect('vader-stop', self._vader_stop, i)
            self.pipes[i]['vad'] = vader

            # Initialize pocketsphinx
            asr = self.pipeline.get_by_name('asr_{0}'.format(i))
            asr.set_property("dict", "{path}/{bot}.dic".format(path = client_path, bot = self.botname))
            asr.set_property("lm", "{path}/{bot}.lm".format(path = client_path, bot = self.botname))
            if configuration.has_key("hmm"):
                if os.path.isdir(configuration["hmm"]):
                    asr.set_property("hmm", configuration["hmm"])
                else:
                    hmm_path = "{path}/{hmm}".format(path = client_path, hmm = configuration["hmm"])
                    if os.path.isdir(hmm_path):
                        asr.set_property("hmm", hmm_path)
            asr.connect('result', self._asr_result, i)
            asr.set_property('configured', 1)
            self.pipes[i]['ps'] = pocketsphinx.Decoder(boxed = asr.get_property('decoder'))

    #-----------------------------------------------------------------------------
    def start(self, recorder):
        # Get recorder
        self.recorder = recorder

        # Start thread
        threading.Thread.start(self)

    #-----------------------------------------------------------------------------
    def run(self):
        """
        Listener main loop
        """
        Speaker.speak("ready")
        self.pipeline.set_state(gst.STATE_PLAYING)

        # Thread loop
        while not self._stopevent.isSet():
            for vader in self.pipes:
                if vader['start'] > 0 and time() >= vader['start'] + VADER_MAX_LENGTH:
                    # Force silent to cut current utterance
                    vader['vad'].set_property('silent', True)
                    vader['vad'].set_property('silent', False)
                    
                    # Manual start (vader_start may be not called after the foreced silence)
                    vader['start'] = time()
                    self.recorder.vader_start()
            sleep(.1)

        # Stop pipeline
        self.pipeline.set_state(gst.STATE_NULL)
        self.pipeline = None

    #-----------------------------------------------------------------------------
    def stop(self):
        """
        Stop listener.
        """
        Speaker.speak('lost_server')

        # Stop everything
        self._stopevent.set()
        self.pipeline.set_state(gst.STATE_NULL)
        if self.recorder is not None:
            self.recorder.stop()

    #-----------------------------------------------------------------------------
    def _vader_start(self, ob, message, pipe_id):
        """
        Vader start detection
        """
        self.pipes[pipe_id]['start'] = time()
        self.recorder.vader_start()

    #-----------------------------------------------------------------------------
    def _vader_stop(self, ob, message, pipe_id):
        """
        Vader stop detection
        """
        self.pipes[pipe_id]['start'] = 0
        self.recorder.vader_stop()

    #-----------------------------------------------------------------------------
    def _asr_result(self, asr, text, uttid, pipe_id):
        """
        Result from pocketsphinx : checking keyword recognition
        """
        # Get score from decoder
        dec_text, dec_uttid, dec_score = self.pipes[pipe_id]['ps'].get_hyp()

        # Detection must have a minimal score to be valid
        if dec_score != 0 and dec_score < self.keyword_score:
            log.msg("I recognized the {word} keyword but I think it's a false positive according the {score} score".format(word = self.botname, score = dec_score))
            return

        # Activate recorder
        self.recorder.activate()

        # Logs
        self.scores.append(dec_score)
        log.msg("======================")
        log.msg("{word} keyword detected".format(word = self.botname))
        log.msg("score: {score} (min {min}, moy {moy}, max {max})".format(score = dec_score, min = min(self.scores), moy = sum(self.scores) / len(self.scores), max = max(self.scores)))

    #-----------------------------------------------------------------------------
    def get_pipeline(self):
        """
        Return Gstreamer pipeline
        """
        return self.pipeline

# --------------------- End of listener.py  ---------------------

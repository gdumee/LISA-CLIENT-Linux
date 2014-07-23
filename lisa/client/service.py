# -*- coding: UTF-8 -*-
#-----------------------------------------------------------------------------
# project     : Lisa client
# module      : client
# file        : service.py
# description : Lisa client twisted service
# author      : G.Dumee
#-----------------------------------------------------------------------------
# copyright   : Neotique
#-----------------------------------------------------------------------------


#-----------------------------------------------------------------------------
# Imports
#-----------------------------------------------------------------------------
from twisted.python import log
import signal
gobjectnotimported = False
try:
    from dbus.mainloop.glib import DBusGMainLoop
    DBusGMainLoop(set_as_default=True)
    import gobject
    import pygst
    pygst.require('0.10')
    gobject.threads_init()
    from lisa.client import lib
    from lib import Listener
    from lib import Player
    from lib import Recorder
    from lib import Speaker
except:
    gobjectnotimported = True
from twisted.internet import ssl, utils
from twisted.internet.protocol import ReconnectingClientFactory
from twisted.internet.defer import inlineCallbacks, DeferredQueue
from twisted.application.internet import TCPClient
from twisted.protocols.basic import LineReceiver
from twisted.application import internet, service
from twisted.internet import reactor
from lisa.client.ConfigManager import ConfigManagerSingleton
import json, os
from OpenSSL import SSL
import platform


#-----------------------------------------------------------------------------
# Globals
#-----------------------------------------------------------------------------
PWD = os.path.dirname(os.path.abspath(__file__))
configuration = None
LisaFactory = None


#-----------------------------------------------------------------------------
# LisaClient
#-----------------------------------------------------------------------------
class LisaClient(LineReceiver):
    """
    Lisa TCP client
    """
    def __init__(self):
        self.factory = None
        self.configuration = ConfigManagerSingleton.get().getConfiguration()
        self.listener = None
        self.debug_input = False
        self.debug_output = False
        if self.configuration.has_key("debug"):
            if self.configuration["debug"].has_key("debug_input"):
                self.debug_input = self.configuration["debug"]["debug_input"]
            if self.configuration["debug"].has_key("debug_output"):
                self.debug_output = self.configuration["debug"]["debug_output"]
        self.name = platform.node()
        self.zone = ""
        if self.configuration.has_key("zone"):
            self.zone = self.configuration['zone']

    #-----------------------------------------------------------------------------
    def sendToServer(self, jsonData):
        # Add info to json
        jsonData['from'] = self.name,
        jsonData['zone'] = self.zone,
        jsonData['to'] = 'Server'

        if self.debug_output:
            log.msg('OUTPUT: {0}'.format(jsonData))

        # Send line to the server
        self.sendLine(json.dumps(jsonData))

    #-----------------------------------------------------------------------------
    def sendChat(self, message, outcome = None):
        json = {'type': 'chat', 'message': message, 'outcome': outcome}
        self.sendToServer(json)

    #-----------------------------------------------------------------------------
    def lineReceived(self, data):
        """
        Data received callback
        The nolistener in configuration is here to let the travis build pass without loading gst
        """
        datajson = json.loads(data)
        if self.debug_input == True:
            log.msg("INPUT: {0}".format(str(datajson)))

        if datajson.has_key("type"):
            datajson['type'] = datajson['type'].lower()
            if datajson['type'] == 'chat':
                if datajson.has_key('nolistener') == False:
                    Speaker.speak(datajson['message'])

            if datajson['type'].lower() == 'error':
                log.err(datajson['message'])
                if datajson.has_key('nolistener') == False:
                    Speaker.speak(datajson['message'])

            elif datajson['type'] == 'command':
                datajson['command'] = datajson['command'].lower()
                if datajson['command'] == 'login ack':
                    # Get Bot name
                    botname = datajson['bot_name']
                    log.msg("setting botname to {0}".format(botname))
                    self.botname = botname

                    # Send TTS
                    if datajson.has_key('nolistener') == False:
                        # Create
                        self.listener = Listener(lisa_client = self)
                        self.recorder = Recorder(lisa_client = self)
                        
                        # Start
                        Speaker.start()
                        self.listener.start(self.recorder)
                        self.recorder.start(self.listener)

                elif datajson['command'] == 'ask':
                    if datajson.has_key('nolistener') == False and datajson.has_key('message'):
                        Speaker.speak(datajson['message'])

                    # Set recorder in continuous mode
                    if datajson.has_key('nolistener') == False and self.recorder:
                        wit_context = {}
                        if datajson.has_key('wit_context') == True:
                            wit_context = datajson['wit_context']
                        self.recorder.set_continuous_mode(enabled = True, wit_context = wit_context)

                elif datajson['command'] == 'kws':
                    if datajson.has_key('nolistener') == False and datajson.has_key('message'):
                        Speaker.speak(datajson['message'])

                    # Set KWS mode
                    if datajson.has_key('nolistener') == False and self.recorder:
                        wit_context = {}
                        if datajson.has_key('wit_context') == True:
                            wit_context = datajson['wit_context']
                        self.recorder.set_continuous_mode(enabled = False, wit_context = wit_context)

        else:
            # Send to TTS queue
            if datajson.has_key('nolistener') == False:
                Speaker.speak(datajson['body'])

    #-----------------------------------------------------------------------------
    def connectionMade(self):
        """
        Callback on established connections
        """
        log.msg('Connected to the server.')

        # Set SSL encryption
        if self.configuration.has_key('enable_secure_mode') and self.configuration['enable_secure_mode'] == True:
            ctx = ClientTLSContext()
            self.transport.startTLS(ctx, self.factory)

        # Login to server
        json = {'type': 'command', 'command': "login req"}
        self.sendToServer(json)

    #-----------------------------------------------------------------------------
    def connectionLost(self, reason):
        """
        Callback on connection loss
        """
        # Stop listener
        log.msg("Lost connection with server : {0}".format(reason.getErrorMessage()))
        if self.listener:
            self.listener.stop()


#-----------------------------------------------------------------------------
# LisaClientFactory
#-----------------------------------------------------------------------------
class LisaClientFactory(ReconnectingClientFactory):
    # Create protocol
    active_protocol = None

    # Warn about failure on first connection to the server
    first_time = True

    #-----------------------------------------------------------------------------
    def Init(self):
        self.configuration = ConfigManagerSingleton.get().getConfiguration()

    #-----------------------------------------------------------------------------
    def startedConnecting(self, connector):
        pass

    #-----------------------------------------------------------------------------
    def buildProtocol(self, addr):
        # Reset retry delay
        self.resetDelay()

        # We don't need a "no connection" warning anymore
        self.first_time = False

        # Return protocol
        self.active_protocol = LisaClient()
        return self.active_protocol

    #-----------------------------------------------------------------------------
    def clientConnectionLost(self, connector, reason):
        # Retry connection
        log.err('Lost connection.  Reason: {0}'.format(reason.getErrorMessage()))
        ReconnectingClientFactory.clientConnectionLost(self, connector, reason)

    #-----------------------------------------------------------------------------
    def clientConnectionFailed(self, connector, reason):
        # Warn on first failure
        if self.first_time == True:
            Speaker.start()
            Speaker.speak("no_server")
            Speaker.stop()
            self.first_time = False

        # Retry
        self.resetDelay()
        log.err('Connection failed. Reason: {0}'.format(reason.getErrorMessage()))
        ReconnectingClientFactory.clientConnectionFailed(self, connector, reason)


#-----------------------------------------------------------------------------
# LisaClientFactory
#-----------------------------------------------------------------------------
class ClientTLSContext(ssl.ClientContextFactory):
    isClient = 1
    def getContext(self):
        return SSL.Context(SSL.TLSv1_METHOD)


#-----------------------------------------------------------------------------
# LisaClientFactory
#-----------------------------------------------------------------------------
class CtxFactory(ssl.ClientContextFactory):
    def getContext(self):
        self.method = SSL.SSLv23_METHOD
        ctx = ssl.ClientContextFactory.getContext(self)
        ctx.use_certificate_file(os.path.normpath(PWD + '/configuration/ssl/client.crt'))
        ctx.use_privatekey_file(os.path.normpath(PWD + '/configuration/ssl/client.key'))
        return ctx


# Creating MultiService
application = service.Application("LISA-Client")

#-----------------------------------------------------------------------------
# Handle Ctrl-C
#-----------------------------------------------------------------------------
def sigint_handler(signum, frame):
    global LisaFactory

    # Unregister handler, next Ctrl-C will kill app
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    # Stop factory
    LisaFactory.stopTrying()

    # Stop reactor
    reactor.stop()

    # Stop speaker
    Speaker.stop()

#-----------------------------------------------------------------------------
# Make twisted service
#-----------------------------------------------------------------------------
def makeService(config):
    global LisaFactory

    # Get configuration
    if config['configuration']:
        ConfigManagerSingleton.get().setConfiguration(config['configuration'])
    configuration = ConfigManagerSingleton.get().getConfiguration()

    # Check vital configuration
    if configuration.has_key('lisa_url') == False or configuration.has_key('lisa_engine_port_ssl') == False:
        Speaker.start()
        Speaker.speak("error_conf")
        return

    # Multiservice mode
    multi = service.MultiService()
    multi.setServiceParent(application)

    # Ctrl-C handler
    signal.signal(signal.SIGINT, sigint_handler)

    # Create factory
    LisaFactory = LisaClientFactory()
    LisaFactory.Init()

    # Start client
    if configuration.has_key('enable_secure_mode') and configuration['enable_secure_mode'] == True:
        lisaclientService = internet.TCPClient(configuration['lisa_url'], configuration['lisa_engine_port_ssl'], LisaFactory, CtxFactory())
    else:
        lisaclientService = internet.TCPClient(configuration['lisa_url'], configuration['lisa_engine_port'], LisaFactory)
    lisaclientService.setServiceParent(multi)

    return multi

# --------------------- End of service.py  ---------------------

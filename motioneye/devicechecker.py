
import os
import logging
import datetime
import signal
import multiprocessing
import requests
import re
import subprocess

from tornado.ioloop import IOLoop


CHECK_DEVICES_TIMEOUT = 120
WEBHOOK_URL = 'https://hooks.slack.com/services/xxx'
KNOWN_MACS = {
    'c0:ee:fb:fb:cb:b4': "DJ's Phone",
    '04:f7:e4:84:91:f2': "PD's Phone",
}


class DeviceChecker(object):
    """
    Device checker checks for devices connected to the network and
    will enable or disable motion detection depending on whether
    those devices are present.

    """
    def __init__(self):
        # TODO: this should depend on initial config
        self._enabled = None
        self._clear_process()

    def device_checker_callback(self):
        if self._process is not None:
            logging.warning("Device checker already running!")
            return

        logging.debug('starting device checking process...')

        self._parent_pipe, self._child_pipe = multiprocessing.Pipe(duplex=False)
        self._process = multiprocessing.Process(target=do_device_check, args=(self._child_pipe, ))
        self._process.start()

        # poll the subprocess to see when it has finished
        self._started = datetime.datetime.now()
        self.poll_process()

    def _clear_process(self):
        self._process = None
        self._child_pipe = None
        self._parent_pipe = None

    def poll_process(self):
        io_loop = IOLoop.instance()
        if self._process.is_alive():  # not finished yet
            now = datetime.datetime.now()
            delta = now - self._started
            if delta.seconds < CHECK_DEVICES_TIMEOUT:
                io_loop.add_timeout(datetime.timedelta(seconds=5), self.poll_process)

            else:  # process did not finish in time
                logging.error('timeout waiting for the device checking process to finish')
                try:
                    os.kill(self._process.pid, signal.SIGTERM)

                except:
                    pass  # nevermind

                self._clear_process()

        else:  # finished
            if self._parent_pipe.poll():
                found_devices = self._parent_pipe.recv()
                logging.debug("device checker found %d devices", len(found_devices))

                enable = len(found_devices) == 0 and not self._enabled
                disable = len(found_devices) > 0 and (self._enabled or self._enabled is None)
                if enable or disable:
                    # state has changed
                    if enable:
                        msg = "No devices found on network -> enabling motion detection"

                        # TODO: enable motion detection

                        self._enabled = True

                    else:
                        msg = "Device(s) found on network ({0}) -> disabling motion detection".format(", ".join(found_devices))

                        # TODO: disable motion detection

                        self._enabled = False

                    logging.debug(msg)
                    notify_slack(msg)

                else:
                    logging.debug("no change in device checker")

            else:
                logging.error("no message to receive from device checker process")

            self._clear_process()


# instance of device checker
instance = DeviceChecker()


# create a subprocess to check for devices
def do_device_check(pipe):
    command = ["arp-scan", "-I", "enp0s31f6", "-l", "-r", "10"]
    output = subprocess.check_output(command, universal_newlines=True)

    found_devices = []
    for mac in KNOWN_MACS.keys():
        if mac in output:
            found_devices.append(KNOWN_MACS[mac])

    pipe.send(found_devices)

    pipe.close()


def notify_slack(message):
    slack_data = {'text': message}
    response = requests.post(WEBHOOK_URL, json=slack_data)
    if response.status_code != 200:
        logging.error("Request to slack returned an error %s, the response is:\n%s", response.status_code, response.text)

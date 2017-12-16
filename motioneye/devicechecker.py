
import os
import logging
import datetime
import signal
import multiprocessing
import re
import subprocess

from tornado.ioloop import IOLoop

import config
import utils
import remote
import motionctl
import slack
import settings


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
            if delta.seconds < settings.DEVICE_CHECKER_TIMEOUT:
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
                        self._enabled = True

                    else:
                        msg = "Device(s) found on network ({0}) -> disabling motion detection".format(", ".join(found_devices))
                        self._enabled = False

                    logging.debug(msg)

                    # enable/disable motion detection
                    self.set_motion_detection()

                    slack.post(msg)

                else:
                    logging.debug("no change in device checker")

            else:
                logging.error("no message to receive from device checker process")

            self._clear_process()

    def set_motion_detection(self):
        """Enable or disable motion detection."""
        # loop over all cameras
        for camera_id in config.get_camera_ids():
            logging.debug("setting motion detection for camera {0}".format(camera_id))

            # get the config for this camera
            local_config = config.get_camera(camera_id)
            if utils.is_local_motion_camera(local_config):
                logging.debug("local camera...")
                logging.debug("LOCAL CONFIG:\n%r", local_config)

                local_config['@motion_detection'] = self._enabled
                logging.debug("LOCAL CONFIG AFTER SET:\n%r", local_config)

                # set config
                logging.debug("calling config.set_camera")
                config.set_camera(camera_id, local_config)

                # restart motion
                logging.debug("restarting motion")
                motionctl.stop()
                motionctl.start()

            else:
                status = "on" if self._enabled else "off"
                remote.set_motion_detection(local_config, status)



# instance of device checker
instance = DeviceChecker()


# create a subprocess to check for devices
def do_device_check(pipe):
    command = ["arp-scan", "-I", "enp0s31f6", "-l", "-r", "10"]
    output = subprocess.check_output(command, universal_newlines=True).lower()

    macs_list = [mac.lower() for mac in settings.DEVICE_CHECKER_MACS.split(",")]

    found_devices = []
    for mac in macs_list:
        if mac in output:
            found_devices.append(mac)

    pipe.send(found_devices)

    pipe.close()

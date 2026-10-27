from PySide6.QtCore import QThread, Signal
from BMSToolBackend import *

class CANWorker(QThread):
    formattedDataReady = Signal(object)  # emits ic data when done
    decodedDataReady = Signal(object)
    rawDataReady = Signal(object)
    error = Signal(str)

    def __init__(self, candapter, msgLen=29):
        super().__init__()
        self.candapter = candapter
        self.msgLen = msgLen

    def run(self):
        while not self.isInterruptionRequested():
            try:
                ic = formatCANMessage(self.candapter, self.msgLen)

                if self.isInterruptionRequested():
                    break

                decodedIC = decode_formatted_data(ic)

                rawCAN = formatCANMessage(self.candapter, self.msgLen)

                self.formattedDataReady.emit(ic)
                self.decodedDataReady.emit(decodedIC)

                self.rawDataReady.emit(rawCAN)
            except Exception as e:
                self.error.emit(str(e))
            self.msleep(100)
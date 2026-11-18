from PySide6.QtWidgets import *
from PySide6.QtGui import *
from PySide6.QtCore import *
from pyqtLE import *
from BMSToolBackend import *
from BMSToolCANWorker import *
from LE import *
import sys
import pyqtgraph as pg
import pyqtgraph.exporters


#baudrates: 125000,       250000,       500000,       1000000
#           125 kBit/sec, 250 kBit/sec, 500 kBit/sec, 1 MBit/sec

currentIndex = 0


# this is just used for testing the graph, if its still here after the graph reads from can it means I forgot to remvoe it
fakeCan = {'0xc0': (['00', '00', '00', '00', '01', '00', '00', '00'], 
                    1763154300.3749294), 
            '0xa1': (['26', '01', 'B8', '0B', 'B8', '0B', '18', '02'], 
                    1763154300.375279), 
            '0xa3': (['F3', 'CD', '37', '1F', '10', '00', '00', '00'], 
                    1763154300.3756359), 
            '0xa4': (['00', '00', '00', '00', '00', '01', '00', '00'], 
                    1763154300.375932)
        }

class MainWindow(QWidget):
    # This class' main purpose is to draw the main window and its associated functionality

    # Comport is set to an impossible value so we can autodetect later
    comPort = 'COM-1'

    #baud is set on the frontend
    canBaud = 0

    #hardcoded because I found no way to change it.
    SERIALBAUDRATE = 9600
    # The three above values are all to ensure the candapter can connect to the BMS

    # Base can ID is B001, this converts that to an int
    baseID = int('B001', 16)
    #below are default values, they can be configured on the front end
    totalIC = 2 
    totalCells = 14
    
    def __init__(self):
        # general initilization. Draws what the program looks like before you create or load a file
        
        super().__init__()

        versionNumber = "0.1.0"

        self.setWindowTitle(f'MR BMS Tool {versionNumber}')

        self.setWindowIcon(QIcon("TempIco.png"))

        self.layout = QGridLayout(self)


        self.candapter = None     # reference to the connected CAN adapter
        self.worker = None

        self.canRowMap = {}


        tabNames = ["Battery Profile",
                    "Charging/Config",
                    "Live CAN Data",
                    "Live Graph/Data Logging",
                    "Live Cell Data",
                    "Diagnostic Trouble Codes"]

        self.tabSystem = QTabWidget()

        self.tabs = []

        for i in tabNames:
            self.tabs.append(QWidget())

            self.tabSystem.addTab(self.tabs[tabNames.index(i)], i)

        # Connects the clicking of the tabs to self.tabIndex, 
        # this is the start of the process of updating the live CAN data
        self.tabSystem.tabBarClicked.connect(self.tabIndex)

        '''
        # Left for shame purposes. I spent a month trying to fix the graph only for the problem
        # to be this loop. In an attempt to be efficient I wasted more time. DON'T DO THIS!
        
        for i in self.tabs:
            i.setLayout([self.makeTabZero(), 
                         self.makeTabOne(), 
                         self.makeTabTwo(), 
                         self.makeTabThree(), 
                         self.makeTabFour(), 
                         self.makeTabFive(), 
                         self.makeTabSix()]
                         [self.tabs.index(i)])
        '''

    
        self.tabs[0].setLayout(self.makeTabZero())
        self.tabs[1].setLayout(self.makeTabOne())
        self.tabs[2].setLayout(self.makeTabTwo())
        self.tabs[3].setLayout(self.makeTabThree())
        self.tabs[4].setLayout(self.makeTabFour())
        self.tabs[5].setLayout(self.makeTabFive())
        #self.tabs[6].setLayout(self.makeTabSix())


        self.layout.addWidget(self.tabSystem)

        self.setLayout(self.layout)


    def closeEvent(self, event):
        # stops the worker and closes the CAN bus
        self.stopWorker()
        if self.candapter:
            self.candapter.closeCANBus()
        event.accept()


    def startWorker(self):
        # starts the worker on a background thread getting data from CAN

        if self.worker and self.worker.isRunning():
            return  # already running
        self.worker = CANWorker(self.candapter)

        # when the decoded data is ready send it to onDataReady for processing
        self.worker.decodedDataReady.connect(self.onBatteryVoltageReady)

        # same thing but for raw data
        self.worker.rawDataReady.connect(self.onRAWCANReady)

        self.worker.error.connect(lambda e: print(f"[ERROR] {e}"))
        self.worker.start()

    def stopWorker(self):
        # Safely stops the worker
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
            self.worker.quit()


    def tabIndex(self, index):
        # Makes the local index global for use later
        # and checks if the user is in a tab that requires live data

        global currentIndex
        currentIndex = index

        if index != 0 and self.candapter:
            self.startWorker()
        else:
            self.stopWorker()

    def onRAWCANReady(self, raw):
        if raw is None:
            print("[WARN] No data received")
            return

        try:
            self.genericCANTable.setUpdatesEnabled(False)  # avoid flicker while updating

            for msg in raw:
                can_id = msg['id']

                # New ID -> append a row and remember it
                if can_id not in self.canRowMap:
                    row = self.genericCANTable.rowCount()
                    self.genericCANTable.insertRow(row)
                    self.canRowMap[can_id] = row
                    self.genericCANTable.setItem(row, 0, QTableWidgetItem(str(can_id)))
                    self.genericCANTable.setItem(row, 1, QTableWidgetItem(str(len(msg['data']))))
                else:
                    row = self.canRowMap[can_id]

                # Update the data bytes for that row
                for j, byte in enumerate(msg['data']):
                    self.genericCANTable.setItem(row, 2 + j, QTableWidgetItem(str(byte)))

                # Update timestamp
                self.genericCANTable.setItem(row, 11, QTableWidgetItem(str(msg['timestamp'])))

        except (IndexError, TypeError, KeyError) as e:
            print(f"[ERROR] onRAWCANReady failed: {e}")

        finally:
            self.genericCANTable.setUpdatesEnabled(True)

    def onBatteryVoltageReady(self, ic):
        # formats the data from the CAN bus and puts it on the frontend

        if ic is None:
            print("[WARN] No data received")
            return

        allVoltages = []
        try:
            for i in range(0, int((bmsValueTransfer.TOTAL_AD68 / 2))):
                ic_dict, cells = ic[i]

                item = None

                if ic_dict.get('type') == 'ic_status':
                    ic_val = ic_dict['v_segment_V']
                    self.cellDataArray[i].setItem(0, 0, QTableWidgetItem(f"{ic_val:.3f}"))

                for col, cell in enumerate(cells, start=1):
                    # adds data to the table in the front end
                    if cell.get('type') == 'cell':
                        cell_val = cell['voltage_V']
                        item = QTableWidgetItem(f"{cell_val:.3f}")

                        # changes the colors depending on if balancing or faulting
                        if cell.get('cell_fault'):
                            item.setBackground(QBrush(QColor(230, 70, 70)))
                            item.setForeground(QBrush(QColor(255, 255, 255)))
                        elif cell.get('is_discharging'):
                            item.setBackground(QBrush(QColor(255, 235, 130)))


                        self.cellDataArray[i].setItem(0, col, item)
                        allVoltages.append((cell_val, i, col))

                self.cellDataArray[i].viewport().update()

            # calculates the min, max, avg, and delta and displays it in the header portion
            # the calcualtions should lowkey be done NOT in the frontend but im lazy
            if allVoltages:
                max_v, max_ic, max_col = max(allVoltages, key=lambda t: t[0])
                min_v, min_ic, min_col = min(allVoltages, key=lambda t: t[0])
                avg_v = sum(v for v, _, _ in allVoltages) / len(allVoltages)
                delta_v = max_v - min_v

                self.voltageHighOne.setText(f"Highest Cell Volt: {max_v:.3f}")
                self.voltageLowOne.setText(f"Lowest Cell Volt: {min_v:.3f}")
                self.voltageAvgOne.setText(f"Avg Cell Volt: {avg_v:.3f}")
                self.voltageDeltaOne.setText(f"Delta Cell Volt: {delta_v:.3f}")

                self.voltageHighFour.setText(f"Highest Cell Volt: {max_v:.3f}")
                self.voltageLowFour.setText(f"Lowest Cell Volt: {min_v:.3f}")
                self.voltageAvgFour.setText(f"Avg Cell Volt: {avg_v:.3f}")
                self.voltageDeltaFour.setText(f"Delta Cell Volt: {delta_v:.3f}")



        except (IndexError, TypeError, KeyError) as e:
            print(f"[ERROR] onBatteryVoltageReady failed: {e}")


    def makeGraph(self):
        self.plotGraph = pg.PlotWidget()
        self.plotGraph.showGrid(x=True, y=True)

        # Axis labels (defaults)
        self.plotGraph.setLabel('left', ' ')
        self.plotGraph.setLabel('bottom', ' ')

        # Add legend ONCE
        self.legend = self.plotGraph.addLegend()

        self.plotGraph.setBackground("#292929")

        graphingPen = pg.mkPen(color='#f1b82d', width=2)

        # Create an EMPTY line we will reuse
        self.plotLine = self.plotGraph.plot(
            [],
            [],
            pen=graphingPen,
            #symbol="star",
            #symbolSize=15,
            #symbolBrush="w",
            name="No Data"
        )

        return self.plotGraph

        
    def onAxisSelectionChanged(self):
        yAxis = self.ySelection.currentText()
        xAxis = self.xSelection.currentText()

        print(f"Selected Y: {yAxis}, X: {xAxis}")

        styles = {"color": "white", "font-size": "18px"}

        # Get data for BOTH axes
        xData = self.getXDataForSelection(xAxis)
        yData = self.getYDataForSelection(yAxis)

        # Update axis labels
        self.plotGraph.setLabel('left', yAxis, **styles)
        self.plotGraph.setLabel('bottom', xAxis, **styles)

        # Update plot + legend (Y describes the line)
        self.plotLine.setData(xData, yData, name=yAxis)


    def getXDataForSelection(self, selection):
        returnValues = []
        
        if selection == "Time (min)":
            returnValues = list(range(60))

        # Future examples:
        # elif selection == "Time (sec)":
        #     returnValues = list(range(0, 600, 10))

        return returnValues


    def getYDataForSelection(self, selection):
        returnValues = []
        
        if selection == "Temperature (°C)":
            returnValues = [20 + i * 0.1 for i in range(60)]

        elif selection == "Inverter Temp (°C)":
            returnValues = [30 + i * 0.05 for i in range(60)]

        elif selection == "Pack Voltage (V)":
            returnValues = [350 + i * 0.2 for i in range(60)]

        elif selection == "Pack Amperage (A)":
            returnValues = [10 + i * 0.3 for i in range(60)]

        return returnValues
    
    
    def exportGraphImage(self):
        options = QFileDialog.Options()

        dlg = QMessageBox(self)
        windowTitle = ""
        windowText = ""
        windowIcon = None

        exporter = pg.exporters.ImageExporter(self.plotGraph.plotItem)

        # save to file
        directory = QFileDialog.getSaveFileName(self, "Save File", "", "Image Files (*.png);;All Files (*)", options=options)
        
        if directory[0] != '':
            exporter.export(directory[0])

            windowTitle = "Success!"
            windowText = "The image was exported!"
            windowIcon = QMessageBox.NoIcon

        else:
            windowTitle = "ERROR!"
            windowText = "The image failed failed to export!\nPlease try again."
            windowIcon = QMessageBox.Warning

        
        dlg.setWindowTitle(windowTitle)
        dlg.setText(windowText)
        dlg.setStandardButtons(QMessageBox.Ok)
        dlg.setIcon(windowIcon)
        dlg.exec()


    def displayErrorCodes(self):
        self.troubleCodeArea.addWidget(QLabel(str(fakeCan)))


    def makeTabZero(self):
        self.tabZeroLayout = QGridLayout()

        self.index = 0
        self.candapter = None

        comSelect = QComboBox()

        refreshButton = PushButtonLE("Refresh")

        comSelect.addItems(verifyCANDAPTERPresent())

        def refreshComPorts():
            # allows for refreshing if no com detected on startup
            comSelect.clear()
            comSelect.addItems(verifyCANDAPTERPresent())

        refreshButton.clicked.connect(refreshComPorts)

        baudSelect = QComboBox()

        # defines the baudrates that can be used with a frontend version, backend, and then selects what we use by default
        baudRates = ["125 kBit/sec", "250 kBit/sec", "500 kBit/sec", "1 MBit/sec"]

        baudSelect.addItems(baudRates)

        items = {
            baudRates[0]: 125_000,
            baudRates[1]: 250_000,
            baudRates[2]: 500_000,
            baudRates[3]: 1_000_000
        }

        baudSelect.setCurrentIndex(2)

        connectButton = PushButtonLE("Connect")

        ad68box = TextEditLE()
        ad68box.setPlainText("10")

        cellsbox = TextEditLE()
        cellsbox.setPlainText("14")

        # Widgets that shouldn't be changed while connected
        lockableWidgets = [comSelect, refreshButton, baudSelect, ad68box, cellsbox]

        def setConnectedUI(connected):
            # creates the connect/disconnect button
            connectButton.setText("Disconnect" if connected else "Connect")
            for w in lockableWidgets:
                w.setEnabled(not connected)

        def connectToCAN():
            self.comPort = comSelect.currentText()
            self.canBaud = items.get(baudSelect.currentText())

            # this is supposed to be a const, no idea why im changing it to the same value but im too scared to break things
            self.SERIALBAUDRATE = 9600

            try:
                bmsValueTransfer.convertAndSetValues(ad68box.toPlainText(), cellsbox.toPlainText())

                self.rebuildTabFour()
                self.tabFourLayout.update()

                self.candapter = pyCandapter.pyCandapter(self.comPort, self.SERIALBAUDRATE)
                self.candapter.openCANBus(self.canBaud)
                print("Connected to CAN bus.")

            except Exception as e:
                QMessageBox.critical(self, "Connection Error", str(e))
                self.candapter = None

            else:
                setConnectedUI(True)
                QMessageBox.information(self, "Success", "Successfully connected to the CAN bus.")

        def disconnectFromCAN():
            try:
                if self.candapter is not None:
                    self.candapter.closeCANBus()
                    print("Disconnected from CAN bus.")
            except Exception as e:
                QMessageBox.critical(self, "Disconnect Error", str(e))
            else:
                QMessageBox.information(self, "Success", "Successfully disconnected from the CAN bus.")
            finally:
                self.candapter = None
                setConnectedUI(False)

        def toggleConnection():
            if self.candapter is None:
                connectToCAN()
            else:
                disconnectFromCAN()

        connectButton.clicked.connect(toggleConnection)

        self.tabZeroLayout.addWidget(QLabel("COM Number: "), 0, 0)
        self.tabZeroLayout.addWidget(comSelect, 0, 1)
        self.tabZeroLayout.addWidget(refreshButton, 0, 2)

        self.tabZeroLayout.addWidget(QLabel("Baudrate: "), 1, 0)
        self.tabZeroLayout.addWidget(baudSelect, 1, 1)

        self.tabZeroLayout.addWidget(QLabel("Number of AD68: "), 2, 0)
        self.tabZeroLayout.addWidget(ad68box, 2, 1)

        self.tabZeroLayout.addWidget(QLabel("Number of Cells: "), 4, 0)
        self.tabZeroLayout.addWidget(cellsbox, 4, 1)

        self.tabZeroLayout.addWidget(connectButton, 5, 0, 1, 3)

        return self.tabZeroLayout

    def makeTabOne(self):
        global currentIndex

        self.isCharging = False
        self.isBalancing = False

        self.tabOneLayout = QGridLayout()

        chargeBalanceGroup = GroupBoxLE("Charging/Balance")
        chargeBalanceGroupingLayout = QGridLayout()

        def whatIsChecked(checkboxes):
            checkedBoxed = {}

            try:
                
                for i in checkboxes:

                    if i.isChecked():
                        foundChild = configGroup.findChild(TextEditLE, name=(i.objectName() + "_TextEdit"))

                        if foundChild.toPlainText().strip() != "":
                            checkedBoxed[checkboxes.index(i)] = int(foundChild.toPlainText())

            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))

            return checkedBoxed


        def removeCheckmarks(checkboxes):
            for i in checkboxes:
                i.setChecked(False)

        def selectWhatToSend(candapter, canID, currentRadio):
            userFriendlyMessage = ""
            userMessageType = None

            canData = []

            # Wrap a try catch for when not connected to canbus

            match currentRadio:
                case -2:
                    self.isCharging = (not self.isCharging)

                    if self.isCharging:
                        canData = [0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00] # Charge on
                        print("Charging")
                        userFriendlyMessage = "Charging enabled"
                        self.radioChargeButton.setText("Stop Charging")

                    else:
                        canData = [0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00] # Charge off
                        print("NOT Charging")
                        userFriendlyMessage = "Charging disabled"
                        self.radioChargeButton.setText("Start Charging")

                case -3:
                    self.isBalancing = (not self.isBalancing)

                    if self.isBalancing:
                        canData = [0x0D, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00] # Balance on
                        print("Balancing")
                        userFriendlyMessage = "Balancing enabled"
                        self.radioBalanceButton.setText("Stop Balancing")

                    else:
                        canData = [0x0D, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00] # Balance off
                        print("NOT Balancing")
                        userFriendlyMessage = "Balancing disabled"
                        self.radioBalanceButton.setText("Start Balancing")
                        
                case -4:
                    try:
                        print("Config")

                        canData = []
                        
                        checkedDict = whatIsChecked(self.checkboxes)

                        #print(checkedDict)

                        if len(checkedDict) <= 0:
                            raise Exception("You cannot configure zero items.\nPlease select a config option to continue.") 

                        elif len(checkedDict) > 4:
                            bigCheckedList = []

                            for i in checkedDict:
                            
                                bigCheckedList.append(i)

                                bigCheckedList.append(checkedDict[i])

                            #print(bigCheckedList)


                            canData.append(bigCheckedList[:8])

                            canData.append(bigCheckedList[8:16])

                            canData.append(bigCheckedList[16:24])
                            
                            canData.append(bigCheckedList[24:])

                        else:

                            for i in checkedDict:

                                canData.append(i)

                                canData.append(checkedDict[i])

                        print(canData)

                    except Exception as e:
                        QMessageBox.critical(self, "Configuration Error", str(e))
                    
                case _:
                    print("Invalid")

            #print(canID)

            if len(canData) > 0:
                try:
                    sendToCANbus(candapter, canID, canData, True)

                except Exception as e:
                    # Revert state and label since the message never went out
                    if currentRadio == -2:
                        self.isCharging = not self.isCharging
                        self.radioChargeButton.setText("Stop Charging" if self.isCharging else "Start Charging")
                    elif currentRadio == -3:
                        self.isBalancing = not self.isBalancing
                        self.radioBalanceButton.setText("Stop Balancing" if self.isBalancing else "Start Balancing")

                    QMessageBox.critical(self, "CAN Error", str(e))

                else:
                    QMessageBox.information(self, "Success", userFriendlyMessage)

        self.index = 1

        self.checkboxes = []
        self.configTextinputs = []

        configGroup = GroupBoxLE("Config")
        configGroupingLayout = QGridLayout()


        cellDataGroup = GroupBoxLE("Cell Data")
        self.cellDataGroupOne = QGridLayout()


        sendChargeButton = PushButtonLE("SEND TO BMS")

        defaultChargeID = TextEditLE()
        defaultChargeID.setPlainText("0x16086420")


        self.messageSendRadioGroup = QButtonGroup()



        self.radioChargeButton = QRadioButton("Start Charging")
        self.radioChargeButton.clicked.connect(lambda: removeCheckmarks(self.checkboxes))

        self.radioBalanceButton = QRadioButton("Start Balancing")
        self.radioBalanceButton.clicked.connect(lambda: removeCheckmarks(self.checkboxes))

        self.radioConfigButton = QRadioButton("Config")



        self.messageSendRadioGroup.addButton(self.radioChargeButton)
        self.messageSendRadioGroup.addButton(self.radioBalanceButton)
        self.messageSendRadioGroup.addButton(self.radioConfigButton)


        '''
        BALANCING THRESHOLD
        MIN VOLTAGE
        MAX VOLTAGE
        MIN CURRENT
        MAX CURRENT
        MAX TEMP
        MIN TEMP
        MAX IC TEMP
        MIN IC TEMP
        DEBUG VOLTAGE
        DEBUG AUX
        DEBUG CURRENT
        DEBUG MASTER MEASUREMENTS
        
        ENABLE BALANCING
        '''



        ConfigValues = ["BALANCING THRESHOLD",
        "MIN VOLTAGE",
        "MAX VOLTAGE",
        "MIN CURRENT",
        "MAX CURRENT",
        "MAX TEMP",
        "MIN TEMP", 
        "MAX IC TEMP",
        "MIN IC TEMP",
        "DEBUG VOLTAGE",
        "DEBUG AUX",
        "DEBUG CURRENT",
        "DEBUG MASTER MEASUREMENTS"]


        self.resistanceHighOne = QLabel(f"Highest Resistance: {None}")
        self.resistanceLowOne = QLabel(f"Lowest Resistance: {None}")
        self.resistanceAvgOne = QLabel(f"Avg Cell Resistance: {None}")
        self.resistanceDeltaOne = QLabel(f"Delta Cell Resistance: {None}")
        self.cellDataGroupOne.addWidget(self.resistanceHighOne, 0, 0)
        self.cellDataGroupOne.addWidget(self.resistanceLowOne, 1, 0)
        self.cellDataGroupOne.addWidget(self.resistanceAvgOne, 2, 0)
        self.cellDataGroupOne.addWidget(self.resistanceDeltaOne, 3, 0)

        self.voltageHighOne = QLabel(f"Highest Cell Volt: {None}")
        self.voltageLowOne = QLabel(f"Lowest Cell Volt: {None}")
        self.voltageAvgOne = QLabel(f"Avg Cell Volt: {None}")
        self.voltageDeltaOne = QLabel(f"Delta Cell Volt: {None}")
        self.cellDataGroupOne.addWidget(self.voltageHighOne, 0, 1)
        self.cellDataGroupOne.addWidget(self.voltageLowOne, 1, 1)
        self.cellDataGroupOne.addWidget(self.voltageAvgOne, 2, 1)
        self.cellDataGroupOne.addWidget(self.voltageDeltaOne, 3, 1)

        self.packSOCOne = QLabel(f"Pack SOC: {None}")
        self.packCurrentOne = QLabel(f"Pack Current: {None}")
        self.packVoltageOne = QLabel(f"Pack Voltage: {None}")
        self.currentLimitsOne = QLabel(f"Current Limits: {None}")
        self.cellDataGroupOne.addWidget(self.packSOCOne, 0, 2)
        self.cellDataGroupOne.addWidget(self.packCurrentOne, 1, 2)
        self.cellDataGroupOne.addWidget(self.packVoltageOne, 2, 2)
        self.cellDataGroupOne.addWidget(self.currentLimitsOne, 3, 2)


        cellDataGroup.setLayout(self.cellDataGroupOne)
        self.tabOneLayout.addWidget(cellDataGroup, 0, 0, 1, 3)


        for i in range(0,len(ConfigValues)):
            newCheckbox = QCheckBox(ConfigValues[i] + ":")
            newCheckbox.setObjectName(ConfigValues[i])
            newCheckbox.clicked.connect(lambda: self.radioConfigButton.setChecked(True))

            newTextInput = TextEditLE()
            newTextInput.setObjectName(ConfigValues[i] + "_TextEdit")
            
            newTextInput.clicked.connect(lambda currentCheckbox=newCheckbox: currentCheckbox.setChecked(True))
            newTextInput.clicked.connect(lambda: self.radioConfigButton.setChecked(True))


            self.checkboxes.append(newCheckbox)
            self.configTextinputs.append(newTextInput)


        chargeBalanceGroupingLayout.addWidget(self.radioChargeButton, 0, 0, 1, 2)
        chargeBalanceGroupingLayout.addWidget(self.radioBalanceButton, 0, 2, 1, 2)


        chargeBalanceGroup.setLayout(chargeBalanceGroupingLayout)
        self.tabOneLayout.addWidget(chargeBalanceGroup, 0, 3, 1, 2)


        flipswitch = True
        for i in range(0, len(self.checkboxes)):
            configGroupingLayout.addWidget(self.checkboxes[i],
                                        3 + i if flipswitch else 2 + i,
                                        0 if flipswitch else 2)

            configGroupingLayout.addWidget(self.configTextinputs[i],
                                        3 + i if flipswitch else 2 + i,
                                        1 if flipswitch else 4)
            
            flipswitch = (not flipswitch)


        sendChargeButton.clicked.connect(lambda _: selectWhatToSend(self.candapter, int(defaultChargeID.toPlainText(), 16), self.messageSendRadioGroup.checkedId()))


        configGroup.setLayout(configGroupingLayout)
        self.tabOneLayout.addWidget(configGroup, 1, 0, 1, 5)


        self.tabOneLayout.addWidget(QLabel("ID: "), 16, 0)
        self.tabOneLayout.addWidget(defaultChargeID, 16, 1, 1, 4)

        self.tabOneLayout.addWidget(sendChargeButton, 17, 0, 1, 5)

        return self.tabOneLayout

    def makeTabTwo(self):
        global currentIndex

        self.tabTwoLayout = QGridLayout()

        self.index = 2

        self.genericCANTable = QTableWidget()

        def formatSendData(stringToFormat):
            canData = []

            splitString = stringToFormat.split()

            for i in splitString:
                canData.append(int(i))

            return canData

        self.tabTwoLayout.addWidget(QLabel("ID: "),0,0)
        idTextbox = TextEditLE()
        self.tabTwoLayout.addWidget(idTextbox, 0, 1)

        self.tabTwoLayout.addWidget(QLabel("Message: "),0,2)
        messageTextbox = TextEditLE()
        messageTextbox.setPlaceholderText("Separate values via a space")
        self.tabTwoLayout.addWidget(messageTextbox, 0, 3)


        sendMessagebutton = PushButtonLE("Send Message")

        #sendMessagebutton.clicked.connect(lambda _: sendToCANbus(self.candapter, int(idTextbox.toPlainText()), formatSendData(messageTextbox.toPlainText()), True))
        def sendFromTab(*_):
            try:
                canID = int(idTextbox.toPlainText().strip(), 0)   # accepts 291 or 0x123
                sendToCANbus(self.candapter, canID,
                            formatSendData(messageTextbox.toPlainText()),
                            canID > 0x7FF)                       # standard if it fits in 11 bits
            except Exception as e:
                QMessageBox.critical(self, "CAN Error", str(e))

        sendMessagebutton.clicked.connect(sendFromTab)

        self.tabTwoLayout.addWidget(sendMessagebutton, 0, 4)


        self.genericCANTable.setColumnCount(12)

        self.genericCANTable.setRowCount(0)

        self.genericCANTable.setHorizontalHeaderLabels([
            "ID",
            "Length",
            "Byte0",
            "Byte1",
            "Byte2",
            "Byte3",
            "Byte4",
            "Byte5",
            "Byte6",
            "Byte7",
            "Count",
            "Timestamp"
            ])

        
        self.genericCANTable.resizeColumnsToContents()

        self.tabTwoLayout.addWidget(self.genericCANTable,1, 0, 1, 5)

        return self.tabTwoLayout

    def makeTabThree(self):
        self.tabThreeLayout = QGridLayout()
        self.index = 3

        self.ySelection = QComboBox()
        self.ySelection.addItems([
            "Temperature (°C)",
            "Inverter Temp (°C)",
            "Pack Voltage (V)",
            "Pack Amperage (A)"
        ])

        self.xSelection = QComboBox()
        self.xSelection.addItems(["Time (min)"])

        # IMPORTANT: connect selection change
        self.ySelection.currentTextChanged.connect(self.onAxisSelectionChanged)
        self.xSelection.currentTextChanged.connect(self.onAxisSelectionChanged)


        exportButton = PushButtonLE("Export")
        exportButton.clicked.connect(self.exportGraphImage)
        self.tabThreeLayout.addWidget(exportButton, 4, 1)


        # Create graph ONCE
        self.tabThreeLayout.addWidget(self.makeGraph(), 0, 1, 1, 2)

        self.tabThreeLayout.addWidget(QLabel("Y-Axis: "), 2, 1)
        self.tabThreeLayout.addWidget(self.ySelection, 3, 1)

        self.tabThreeLayout.addWidget(QLabel("X-Axis: "), 2, 2)
        self.tabThreeLayout.addWidget(self.xSelection, 3, 2)

        return self.tabThreeLayout

    def makeTabFour(self):
        global currentIndex

        self.tabFourLayout = QGridLayout()

        self.index = 4

        grouping = GroupBoxLE("Live Cell Data")

        self.cellDataGroupFour = QGridLayout()

        self.resistanceHighFour = QLabel(f"Highest Resistance: {None}")
        self.resistanceLowFour = QLabel(f"Lowest Resistance: {None}")
        self.resistanceAvgFour = QLabel(f"Avg Cell Resistance: {None}")
        self.resistanceDeltaFour = QLabel(f"Delta Cell Resistance: {None}")
        self.cellDataGroupFour.addWidget(self.resistanceHighFour, 0, 0)
        self.cellDataGroupFour.addWidget(self.resistanceLowFour, 1, 0)
        self.cellDataGroupFour.addWidget(self.resistanceAvgFour, 2, 0)
        self.cellDataGroupFour.addWidget(self.resistanceDeltaFour, 3, 0)

        self.voltageHighFour = QLabel(f"Highest Cell Volt: {None}")
        self.voltageLowFour = QLabel(f"Lowest Cell Volt: {None}")
        self.voltageAvgFour = QLabel(f"Avg Cell Volt: {None}")
        self.voltageDeltaFour = QLabel(f"Delta Cell Volt: {None}")
        self.cellDataGroupFour.addWidget(self.voltageHighFour, 0, 1)
        self.cellDataGroupFour.addWidget(self.voltageLowFour, 1, 1)
        self.cellDataGroupFour.addWidget(self.voltageAvgFour, 2, 1)
        self.cellDataGroupFour.addWidget(self.voltageDeltaFour, 3, 1)

        self.packSOCFour = QLabel(f"Pack SOC: {None}")
        self.packCurrentFour = QLabel(f"Pack Current: {None}")
        self.packVoltageFour = QLabel(f"Pack Voltage: {None}")
        self.currentLimitsFour = QLabel(f"Current Limits: {None}")
        self.cellDataGroupFour.addWidget(self.packSOCFour, 0, 2)
        self.cellDataGroupFour.addWidget(self.packCurrentFour, 1, 2)
        self.cellDataGroupFour.addWidget(self.packVoltageFour, 2, 2)
        self.cellDataGroupFour.addWidget(self.currentLimitsFour, 3, 2)


        grouping.setLayout(self.cellDataGroupFour)

        grouping.setMaximumHeight(150)


        self.cellDataArray = [ QTableWidget() for i in range(0, int((bmsValueTransfer.TOTAL_AD68 / 2))) ]

        #self.cellDataArray = [ QTableWidget() for i in range(0, 5) ]

        for j in range(len(self.cellDataArray)):

            self.cellDataArray[j].setColumnCount(bmsValueTransfer.TOTAL_CELLS + 1)
            self.cellDataArray[j].setRowCount(2)
            self.cellDataArray[j].setMaximumHeight(125)


            self.cellDataArray[j].setHorizontalHeaderLabels(
                ["Segment Voltage" if i == 0 else f"Cell {i}" for i in range(0, bmsValueTransfer.TOTAL_CELLS + 1)]
            )

            #self.cellDataArray.setVerticalHeader()

            self.cellDataArray[j].setEditTriggers(QAbstractItemView.NoEditTriggers)


        self.tabFourLayout.addWidget(grouping, 0, 0, 1, 3)

        for i in range(len(self.cellDataArray)):

            self.tabFourLayout.addWidget(self.cellDataArray[i], i + 1, 0, 1, 3)

        exportLiveCellValues = PushButtonLE(text='Export Live Cell Values (CSV)')
        #exportLiveCellValues.clicked.connect()

        recordData = PushButtonLE(text='Record Data')
        recordData.setIcon(recordData.style().standardIcon(QStyle.SP_MediaPlay))
        #exportLiveCellValues.clicked.connect()

        stopDataRecording = PushButtonLE(text='Stop Recording')
        stopDataRecording.setIcon(stopDataRecording.style().standardIcon(QStyle.SP_MediaStop))
        #exportLiveCellValues.clicked.connect()

        self.tabFourLayout.addWidget(exportLiveCellValues,(bmsValueTransfer.TOTAL_CELLS + 4),0)
        self.tabFourLayout.addWidget(recordData,(bmsValueTransfer.TOTAL_CELLS + 4),1)
        self.tabFourLayout.addWidget(stopDataRecording,(bmsValueTransfer.TOTAL_CELLS + 4),2)

        return self.tabFourLayout
    
    def rebuildTabFour(self):
        # Remove the old tab widget from the tab system
        self.tabSystem.removeTab(4)

        # Create a new widget and build the layout into it
        newTab = QWidget()
        self.tabs[4] = newTab
        newTab.setLayout(self.makeTabFour())

        # Re-insert it at the correct position
        self.tabSystem.insertTab(4, newTab, "Live Cell Data")
        #self.tabSystem.setCurrentIndex(4)

    def makeTabFive(self):
        global currentIndex

        self.tabFiveLayout = QGridLayout()

        self.index = 1



        self.troubleCodeArea = QVBoxLayout()

        troubleCodeWidget = QWidget()
        troubleCodeWidget.setObjectName("troubleCodeWidget")
        troubleCodeWidget.setLayout(self.troubleCodeArea)


        self.additionalInformationArea = QVBoxLayout()

        additionalInformationWidget = QWidget()
        additionalInformationWidget.setObjectName("additionalInformationWidget")
        additionalInformationWidget.setLayout(self.additionalInformationArea)


        self.activeCellFaultsArea = QVBoxLayout()

        activeCellFaultsWidget = QWidget()
        activeCellFaultsWidget.setObjectName("activeCellFaultsWidget")
        activeCellFaultsWidget.setLayout(self.activeCellFaultsArea)


        self.exportCSV = PushButtonLE("Export Additional Information (CSV)")
        self.clearAllCodes = PushButtonLE("Clear All Codes")

        self.tabFiveLayout.addWidget(troubleCodeWidget, 0, 0)
        self.tabFiveLayout.addWidget(QLabel("==>"), 0, 1)
        self.tabFiveLayout.addWidget(additionalInformationWidget, 0, 2)
        self.tabFiveLayout.addWidget(activeCellFaultsWidget, 0, 3)

        self.tabFiveLayout.addWidget(QLabel("Code Symbol Legend:\n(H) = Historical (Past Occurrence)\n(S) = Stored\n(A) = Active\n(F) = Freeze Frame Data Available"), 1, 0)

        self.tabFiveLayout.addWidget(self.exportCSV, 1, 2)
        self.tabFiveLayout.addWidget(self.clearAllCodes, 4, 0, 1, 4)

        '''
        button = PushButtonLE(text='Refresh')
        button.clicked.connect(self.displayErrorCodes)

        self.tabSixLayout.addWidget(button)
        '''
        return self.tabFiveLayout
    
    '''
    def makeTabSix(self):
        global currentIndex

        self.tabSixLayout = QGridLayout()

        self.index = 6

        return self.tabSixLayout
    '''


    def loadFileButton(self, textBox, fileTypeIndex):
        # loads the file and ensures the data is somewhat valid
        print(textBox)

        options = QFileDialog.Options()

        msg = QMessageBox()

        fileTypes = ["Comma Separated Values (*.csv);;All Files (*)","MP4 (*.mp4);;All Files (*)"]

        directory = QFileDialog.getOpenFileName(self, "Open File", "", fileTypes[fileTypeIndex], options=options)

        if directory[0] != '':
      
            try:
                msg.setText("Successfully loaded file!")
                msg.setWindowTitle("Success")
                msg.exec()

                textBox.setPlainText(directory[0])

            except:
                msg.setText("Could not load Json file.")
                msg.setWindowTitle("Error")
                msg.exec()


if __name__ == "__main__":
    # Executes the app and configures a few small settings

    app = QApplication(sys.argv)

    app.setStyle('Fusion')

    pyi_splash = None
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):

        try:
            import pyi_splash, birthdays
            pyi_splash.update_text(birthdays.returnBirthdays() + "\nLoading...")
            
        except ImportError:
            pyi_splash = None  # Not running from a PyInstaller bundle
        
        #print('running in a PyInstaller bundle')
        stylesheet = loadFile(sys._MEIPASS + "/styles.qss")
    else:
        #print('running in a normal Python process')
        stylesheet = loadFile("dev/styles.qss")

    app.setStyleSheet(stylesheet)
    
    window = MainWindow()
    
    window.showMaximized()

    if pyi_splash:
        pyi_splash.close()

    sys.exit(app.exec())
import pyCandapter, can, signal, serial.tools.list_ports, serial.serialutil, struct
from LE import *


class BMSValues:
    
    def __init__(self, TOTAL_AD68, TOTAL_CELLS):

        self.TOTAL_AD68              = TOTAL_AD68
        self.TOTAL_CELLS             = TOTAL_CELLS
        self.BASE_CAN_ID             = 0xB000

        self.CELL_CAN_ID_BASE        = self.BASE_CAN_ID
        self.CELL_CAN_ID_MAX         = self.CELL_CAN_ID_BASE + self.TOTAL_AD68 * self.TOTAL_CELLS
        self.IC_CAN_ID_BASE          = self.CELL_CAN_ID_MAX #i.e. just BASE_CAN_ID + TOTAL_AD68 * TOTAL_CELLS
        self.IC_CAN_ID_MAX           = self.IC_CAN_ID_BASE + self.TOTAL_AD68

        self.CHARGER_CONFIG_CAN_ID   = 0x1806E5F4

    def convertAndSetValues(self, TOTAL_AD68, TOTAL_CELLS):
        TOTAL_AD68_int = None
        TOTAL_CELLS_int = None

        try:
            TOTAL_AD68_int = int(TOTAL_AD68)

            TOTAL_CELLS_int = int(TOTAL_CELLS)

            self.__init__(TOTAL_AD68_int, TOTAL_CELLS_int)
        
        except TypeError:
            print("wrong type")

        except:
            print("Something went wrong")

        
bmsValueTransfer = BMSValues(2,14)

def readCANbusToFile(candapter, msgLen, id=None):
    dataToSave = []

    i=0
    while i< msgLen:
        message = candapter.readCANMessage(id)
        if message is not None:
            #print(message)
            dataToSave.append(message)
            i+=1

    return dataToSave


def readCANbus(candapter,ID):

    try:
        message = candapter.readCANMessage(ID)
        
        if message is None:
            raise ValueError

        return [message]
    
    except ValueError as e:
        print(e)



def sendToCANbus(candapter, id, data, extended_id):

    if isinstance(data[0], list):
        for i in data:
            message = can.Message(arbitration_id=id, data=i, is_extended_id=extended_id)
            candapter.sendCANMessage(message)

    else:
        message = can.Message(arbitration_id=id, data=data, is_extended_id=extended_id)
        candapter.sendCANMessage(message)


def verifyCANDAPTERPresent():
    comPorts = []

    if len(serial.tools.list_ports.comports()) > 0:

        for i in serial.tools.list_ports.comports():

            if str(i)[0:3] == "COM":
                comPorts.append(str(i)[0:4])

    else:
        comPorts.append("No CANDAPTER detected")

    return comPorts


def rawCANMessage(candapter,msgLen):
    messages = readCANbusToFile(candapter, msgLen)

    formatted = [
        {
            "id": f"0x{msg.arbitration_id:X}",
            "data": [f"{byte:02X}" for byte in msg.data],
            "timestamp": msg.timestamp
        }
        for msg in messages
    ]

    return formatted


def formatCANMessage(candapter,msgLen):
    messages = readCANbusToFile(candapter, msgLen)

    formatted = [
        {
            "id": f"0x{msg.arbitration_id:X}",
            "data": [f"{byte:02X}" for byte in msg.data],
            "timestamp": msg.timestamp
        }
        for msg in messages
    ]


    #candapter.closeCANBus()    

    # baseID = int('B000', 16)
    # totalIC = 2 #make this configurable later
    # totalCells = 14

    ICs = [
        [
            [None, None],                                # Segment Data aka IC Data
            [[None, None] for _ in range(bmsValueTransfer.TOTAL_CELLS)],  # Cell data
        ]
        for _ in range(bmsValueTransfer.TOTAL_AD68)
    ]

    for i in formatted:
        id = int(i['id'], 16)
        if id >= bmsValueTransfer.IC_CAN_ID_MAX:
            pass
        elif id >= bmsValueTransfer.IC_CAN_ID_BASE:
            # Segment data
            IC_Index = id - bmsValueTransfer.IC_CAN_ID_BASE
            ICs[IC_Index][0][0] = i['id']
            ICs[IC_Index][0][1] = i['data']
            
        elif id >= bmsValueTransfer.CELL_CAN_ID_BASE:
            # Cell data
            currentIC = (id - bmsValueTransfer.CELL_CAN_ID_BASE) // bmsValueTransfer.TOTAL_CELLS
            cellIndex = (id - bmsValueTransfer.CELL_CAN_ID_BASE) % bmsValueTransfer.TOTAL_CELLS
            ICs[currentIC][1][cellIndex][0] = i['id']
            ICs[currentIC][1][cellIndex][1] = i['data']

    if __name__ == "__main__":
        print_formatted_CANMessage(ICs)

    return ICs

def print_formatted_CANMessage(ICs):
    try:
        for j in ICs:
            print(f"\n\nic_data: {j[0]}")
            for idx, k in enumerate(j[1]):
                print(f"cell {idx+1}: {k}")
    except:
        print("Type not acceptable")

def decode_cell_message(can_id, data):
    """
    CAN ID: BASE_CAN_ID + ic * TOTAL_CELL + c
    Bytes 0-1: cell voltage (int16, x1000 -> V)
    Bytes 2-3: voltage diff (int16, x1000 -> V)
    Bytes 4-5: cell temp    (int16, x100  -> degC)
    Byte  6:   flags        (bit0=isDischarging, bit1=isCellFault)
    """
    (cell_voltage, voltage_diff, cell_temp, flags) = struct.unpack_from('<hhhB', bytes(data), 0)

    offset = can_id - bmsValueTransfer.BASE_CAN_ID
    ic = offset // bmsValueTransfer.TOTAL_CELLS
    c  = offset %  bmsValueTransfer.TOTAL_CELLS


    return {
        'type':           'cell',
        'ic':             ic,
        'cell':           c,
        'voltage_V':      cell_voltage / 1000.0,
        'voltage_diff_V': voltage_diff / 1000.0,
        'temp_C':         cell_temp    / 100.0,
        'is_discharging': bool(flags & 0x01),
        'cell_fault':     bool(flags & 0x02),
    }


def decode_ic_message(can_id, data):
    """
    CAN ID: BASE_CAN_ID + TOTAL_CELL + ic
    Bytes 0-3: segment voltage (int32, x1000 -> V)
    Bytes 4-5: IC temperature  (int16, x100  -> degC)
    Byte  6:   flags           (bit0=CommsError, bit1=FaultDetected)
    """

    #print(f"\n\n\n\n\n{data}\n\n\n\n\n")

    (v_segment, temp_ic, flags) = struct.unpack_from('<fhB', bytes(data), 0)

    ic = can_id - bmsValueTransfer.IC_CAN_ID_BASE

    return {
        'type':         'ic_status',
        'ic':           ic,
        'v_segment_V':  v_segment,
        'temp_C':       temp_ic   / 100.0,
        'comms_error':  bool(flags & 0x01),
        'fault':        bool(flags & 0x02),
    }


def decode_message(can_id, data):

    if can_id != None:
        fixed_ID = int(can_id, 16)
    else:
        fixed_ID = 0xFFFF

    converted_data = []

    if data != None:
        for i in data:
            converted_data.append(int(i, 16))

    # can_id = formatted_data[0][0][0]
    # data   = msg.data

    # AD29 status (Don't have any)
    # if can_id == AD29_STATUS_ID:
        # return decode_ad29_status_message(data)

    # Charger config
    if fixed_ID == bmsValueTransfer.CHARGER_CONFIG_CAN_ID:
        return {'type': 'charger_config', 'raw': list(converted_data)}

    # IC messages
    if bmsValueTransfer.IC_CAN_ID_BASE <= fixed_ID < bmsValueTransfer.IC_CAN_ID_MAX:
        return decode_ic_message(fixed_ID, converted_data)

    # Cell messages
    if bmsValueTransfer.BASE_CAN_ID <= fixed_ID < bmsValueTransfer.CELL_CAN_ID_MAX:
        return decode_cell_message(fixed_ID, converted_data)

    return {'type': 'unknown', 'id': hex(fixed_ID), 'raw': list(converted_data)}

def decode_formatted_data(formatted_data):
    '''    
    formatted_data = [
        [
            [None, None], # IC, 0 = id, 1 = data
            [[None, None] for _ in range(TOTAL_CELLS)],  # cell, 0 = id, 1 = data
        ]
        for _ in range(TOTAL_AD68)
    ]

    ic = {
        'type':         'ic_status',
        'ic':           ic,
        'v_segment_V':  v_segment,
        'temp_C':       temp_ic   / 100.0,
        'comms_error':  bool(flags & 0x01),
        'fault':        bool(flags & 0x02),
    }

    cell = {
        'type':           'cell',
        'ic':             ic,
        'cell':           c,
        'voltage_V':      cell_voltage / 1000.0,
        'voltage_diff_V': voltage_diff / 1000.0,
        'temp_C':         cell_temp    / 100.0,
        'is_discharging': bool(flags & 0x01),
        'cell_fault':     bool(flags & 0x02),
    }

    decoded_msg = [
        [
            {ic}, # ic = the IC dictionary seen above
            [{cell}] for _ in range(TOTAL_CELLS)],  # cell = the cell dictionary seen above
        ]
        for _ in range(TOTAL_AD68)
    ]
    '''
    decoded_msg = []

    for ic in formatted_data:

        ic_dict = decode_message(ic[0][0], ic[0][1])

        cells = []


        for cell in ic[1]:
            cell_dict = decode_message(cell[0], cell[1])

            cells.append(cell_dict)


        decoded_msg.append([ic_dict, cells])

    return decoded_msg

def backendMain(comPort, canbaudrate, serialbaudrate, msgLen):

    #SERIALBAUDRATE = 9600 #hard coded for testing

    print(f"Com: {comPort}\n serial: {serialbaudrate}\n baudrate: {canbaudrate}")
    
    
    candapter = pyCandapter.pyCandapter(comPort, serialbaudrate)
    
    try:
        candapter.openCANBus(canbaudrate)
    except RuntimeError as e:
        print(e)
        return None


    def signal_handler(sig, frame):
        candapter.closeCANBus()
        exit(0) 

    signal.signal(signal.SIGINT, signal_handler)

    return formatCANMessage(candapter,msgLen)


# B062 = segement voltage for 

# B000 + 7 * 14 + ic (ic should be looped through)


if __name__ == "__main__":
    formatted_CANData = backendMain("COM3", 1_000_000, 9600, 29)

    print(decode_formatted_data(formatted_CANData))

    #print(decode_message(0xB01C, bytes([0xA9, 0xA4, 0xAE, 0x41, 0x00, 0x00, 0x00, 0x00])))
    
    #print(decode_message(0xB000, bytes([0x1D, 0x06, 0x0C, 0x00, 0x00, 0x00, 0x00, 0x00])))
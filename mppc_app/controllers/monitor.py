# ---------------------------------------------------------------------------
import argparse
parser = argparse.ArgumentParser(
    prog="monitor",
    usage="python3 monitor.py <uart ch>",
    description="",
    epilog="end",
    add_help=True,
)
parser.add_argument('uart_ch', type=int, help="Input uart ch")
args = parser.parse_args()
# ---------------------------------------------------------------------------

import sys
import serial
import time

conv_factor_Vb = 1.812*10**-3
conv_factor_volt = 1.812*10**-3
conv_factor_curr = 4.980*10**-3

def hex2vol(hex_value):
    return int(hex_value, 16)*conv_factor_volt

def hex2curr(hex_value):
    return int(hex_value, 16)*conv_factor_curr

def hex2temp(hex_value):
    return ( int(hex_value, 16) * 1.907*10**-5 - 1.035 ) / (-5.5*10**-3)

def vol2hex(vol_value):
    # return hex( int(vol_value/conv_factor_Vb) )
    return format( int(vol_value/conv_factor_Vb), "04x" ).encode()
    

# open port
ser = serial.Serial('/dev/ttyAMA{}'.format(args.uart_ch), baudrate=38400, parity='E', timeout=1)

print("\n------------------------------")
if ser.isOpen():
    print("port opened successfully")
else:
    print("Port open failed")
    sys.exit()

# create command
stx       = b"\x02"
command   = "HPO".encode()
etx       = b"\x03"
check_sum = str( hex(sum(command)+5) )[-2:].encode()
delimiter = b"\x0D"

send_cmd = stx + command + etx + check_sum + delimiter
print("send command:     ", send_cmd)

# send command
ser.write(send_cmd)
ser.flush()

# receive command and interpret it
time.sleep(0.1)
received_cmd = ser.readline()
print("received command: ", received_cmd)

# close port
ser.close()

# cal checksum of received command
cal_checksum = str( hex(sum(received_cmd[:-3])).upper() )[-2:]
received_checksum = received_cmd[-3:-1].decode()
print(f"checksum(cal/rec): {cal_checksum}, {received_checksum}")
print("------------------------------\n")

# analyze received command
print("-- status --------------------")
status = int(received_cmd.decode()[4:8], 16)
for i in range(7):
    print(f"bit{i}: {(status >> i) & 1}")
print("------------------------------\n")

print("-- value ---------------------")
print( "volt: {:.3f} [V]".format( hex2vol(received_cmd.decode()[12:16]) ) )
print( "curr: {:.3f} [mA]".format( hex2curr(received_cmd.decode()[16:20]) ) )
print( "temp: {:.3f} [deg]".format( hex2temp(received_cmd.decode()[20:24]) ) )
print("------------------------------\n")

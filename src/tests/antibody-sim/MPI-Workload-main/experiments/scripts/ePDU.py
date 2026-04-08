import subprocess
import argparse
import time
import pandas as pd

# This method appends the power consumption and time step to the file.
def append_to_file(server_power_file, time_step, power_consumption):
    with open(server_power_file, "a") as file:
        # Write the time step and power consumption as comma-separated values
        file.write(f"{time_step},{power_consumption}\n")


# This method returns power consumption of the machine at the outlet level.
def retrieve_machine_power_consumption(ePDU_ip, outlet):
    # Output: date of observation, time of observation, ouletname, status (on/off), load in tenth of Amps, load in Watts
    command = f"snmpget -v1 -c private -M +. -O vq -m ALL {ePDU_ip} mconfigClockDate.0 mconfigClockTime.0 ePDU2OutletSwitchedInfoName.{outlet} ePDU2OutletSwitchedStatusState.{outlet} ePDU2OutletMeteredStatusLoad.{outlet} ePDU2OutletMeteredStatusActivePower.{outlet}"

    parsed_command = command.split()

    proc1 = subprocess.run(parsed_command, stdout=subprocess.PIPE)
    output = proc1.stdout.decode('utf-8')

    lined_output = output.replace('\n', ',')

    return lined_output.split(',')[5]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="ePDU Power Monitoring", formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    parser.add_argument("-ip", "--epdu-ip", default="192.168.245.202", help="ePDU IP that the machine is connected to")
    parser.add_argument("-o", "--outlet", default=7, type=int, help="the outlet that the machine is plugged into")
    parser.add_argument("-s", "--sampling-time", default=1, type=int, help="sampling time")
    parser.add_argument("-f", "--server-power-file", default="./measured_server_power.csv", help="File to store measured server power", required=True)

    args = parser.parse_args()

    epdu_ip = args.epdu_ip  # IP address of epdu
    outlet = args.outlet  # outlet number
    sampling_time = args.sampling_time  # Wait time between each measurement
    f_measured_server_power = args.server_power_file  # File for storing measured server power consumption data

    # Create the file with headers if it doesn't exist
    with open(f_measured_server_power, "w") as file:
        file.write("timestep,power(w)\n")

    print("Starting power monitoring. Press Ctrl+C to stop.")

    time_step = 0  # Start with t=0

    try:
        power_values = []

        while True:
            power_consumption = retrieve_machine_power_consumption(epdu_ip, outlet)
            power_values.append(power_consumption)
            if len(power_values) >= 60:  # 60 seconds
                avg_power = sum(power_values) 
                append_to_file(f_measured_server_power, time_step, avg_power)
                power_values = []  # Reset the buffer
                time_step += 1
            time.sleep(sampling_time)
    except KeyboardInterrupt:
        print("Monitoring stopped.")
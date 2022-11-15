#!/usr/bin/env python
# -*- coding: utf-8 -*-
# __author__ = "Sébastien Reuiller"
# __licence__ = "Apache License 2.0"

# Python 3, prérequis : pip install pySerial influxdb
#
# Exemple de trame:
# {
#  'BASE': '123456789'       # Index heure de base en Wh
#  'OPTARIF': 'HC..',        # Option tarifaire HC/BASE
#  'IMAX': '007',            # Intensité max
#  'HCHC': '040177099',      # Index heure creuse en Wh
#  'IINST': '005',           # Intensité instantanée en A
#  'PAPP': '01289',          # Puissance Apparente, en VA
#  'MOTDETAT': '000000',     # Mot d'état du compteur
#  'HHPHC': 'A',             # Horaire Heures Pleines Heures Creuses
#  'ISOUSC': '45',           # Intensité souscrite en A
#  'ADCO': '000000000000',   # Adresse du compteur
#  'HCHP': '035972694',      # index heure pleine en Wh
#  'PTEC': 'HP..'            # Période tarifaire en cours
# }


import logging
import time
from datetime import datetime

import requests
import serial
from influxdb import InfluxDBClient

# time to wait before capturing a new frame in second
CAPTURE_FREQUENCY = 60

# clés téléinfo
INT_MESURE_KEYS = ['BASE', 'IMAX', 'HCHC', 'IINST', 'PAPP', 'ISOUSC', 'ADCO', 'HCHP']

# création du logguer
logging.basicConfig(filename='/var/log/teleinfo/releve.log',
level=logging.INFO, format='%(asctime)s %(message)s')
logging.info("Teleinfo starting..")

# connexion a la base de données InfluxDB
client = InfluxDBClient('localhost', 8086)
DB_NAME = "teleinfo"
connected = False
while not connected:
    try:
        logging.info("Database %s exists?" % DB_NAME)
        if not {'name': DB_NAME} in client.get_list_database():
            logging.info("Database %s creation.." % DB_NAME)
            client.create_database(DB_NAME)
            logging.info("Database %s created!" % DB_NAME)
        client.switch_database(DB_NAME)
        logging.info("Connected to %s!" % DB_NAME)
    except requests.exceptions.ConnectionError:
        logging.info('InfluxDB is not reachable. Waiting 5 seconds to retry.')
        time.sleep(5)
    else:
        connected = True


def add_measures(measures):
    points = []
    for measure, value in measures.items():
        point = {
            "measurement": measure,
            "tags": {
                # identification de la sonde et du compteur
                "host": "raspberry",
                "region": "linky"
            },
            "time": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "fields": {
                "value": value
            }
        }
        points.append(point)

    client.write_points(points)


def verif_checksum(data, checksum):
    data_unicode = 0
    for caractere in data:
        data_unicode += ord(caractere)
    sum_unicode = (data_unicode & 63) + 32
    return (checksum == chr(sum_unicode))


def main():
    with serial.Serial(port='/dev/ttyUSB0', baudrate=1200, parity=serial.PARITY_EVEN, stopbits=serial.STOPBITS_ONE,
                       bytesize=serial.SEVENBITS, timeout=1) as ser:

        logging.info("Teleinfo is reading on /dev/ttyUSB0..")

        trame = dict()

        # Get the current line
        first_line = ser.readline()

        while True:
          trame = dict()  # new frame
          logging.debug(f"first line: {first_line}")
          # wait for a new frame
          logging.debug("Wait for the beginning of a frame")
          while b'\x02' not in first_line:  # MOTDETAT line
            first_line = ser.readline()
          logging.debug(f"MOTDETAT line detected: {first_line}")
          # new frame. current line == MOTDETAT

          # take the next line
          line = ser.readline()
          while b'\x02' not in line:  # until we get again the MOTDETAT, we prepare the frame
            logging.debug(f"metric: {line}")
            line_str = line.decode("utf-8")
            try:
                # separation sur espace /!\ attention le caractere de controle 0x32 est un espace aussi
                [key, val, *_] = line_str.split(" ")

                # supprimer les retours charriot et saut de ligne puis selectionne le caractere
                # de controle en partant de la fin
                checksum = (line_str.replace('\x03\x02', ''))[-3:-2]

                if verif_checksum(f"{key} {val}", checksum):
                    # creation du champ pour la trame en cours avec cast des valeurs de mesure en "integer"
                    trame[key] = int(val) if key in INT_MESURE_KEYS else val

                if "ADCO" in trame:
                  trame.pop("ADCO")

            except Exception as e:
                logging.error("Exception : %s" % e, exc_info=True)
                logging.error("%s %s" % (key, val))

            # take the next line
            line = ser.readline()

          logging.debug(str(trame))
          # insert frame in influx
          add_measures(trame)
          # # Optional, but recommended: sleep 10 ms (0.01 sec) once per loop to let
          # # other threads on your PC run during this time.
          logging.debug(f"Wait '{CAPTURE_FREQUENCY}' seconds before reading again")
          time.sleep(CAPTURE_FREQUENCY)


if __name__ == '__main__':
    if connected:
        main()

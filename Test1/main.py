from datetime import datetime
from datetime import timezone 
import datetime 
import time
import paho.mqtt.client as mqtt
import json
import base64
import cv2

#-------------------------------------------------------------
#COSAS DE MQTT
#-------------------------------------------------------------
client = mqtt.Client("pruebasDistribuidos")
client.connect("localhost", port=30510)

def get_image_array():
    images = []
    for i in range(1, 62):
        with open("images/image ({}).jpg".format(i),'rb') as file:
            filecontent = file.read()
            encoded = base64.b64encode(filecontent)
            base = str(encoded)
            images.append(base)
    return images


def time_to_str(): return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def sendData_ditto_protocol(group, rep, msg, image, time):
    message = {
        "topic" : "distributed/imagerecognition/things/twin/commands/merge",
        "headers":{
            "content-type": "application/merge-patch+json"
        },
        "path": "/features",
        "value": {
            "group": {
                "properties": {
                    "value": group
                }
            },
            "rep": {
                "properties": {
                    "value": rep
                }
            },
            "msg": {
                "properties": {
                    "value": msg
                }
            },
            "image": {
                "properties": {
                    "value": image
                }
            },
            "timestamp": {
                "properties": {
                    "value": time
                }
            }
        }
    }
    message = json.dumps(message)
    client.publish("telemetry/distributed", payload = message)


def main():
    images = get_image_array()
    count = 0
    for group in range(0, 11):
        print("Bloque {}".format(group))
        for rep in range(0, 10):
            print("Repeticion {}".format(rep))
            
            num_messages = 1 if group == 0 else group * 10
            for message in range(0, num_messages):
                dt = datetime.datetime.now(timezone.utc)  
                utc_time = dt.replace(tzinfo=timezone.utc) 
                utc_timestamp = utc_time.timestamp()
                sendData_ditto_protocol(group, rep, message, images[0], utc_timestamp)
                count += 1
                print("{}/5510".format(count))
                time.sleep(0.1)
            time.sleep(10)
        time.sleep(15)

if __name__ == "__main__":
    main()
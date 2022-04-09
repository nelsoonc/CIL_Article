"""
MAIN SCRIPT
Performance Investigation on AV based on CIL
@author : nelsoonc

Continuation of Undergraduate Thesis
Nelson Changgraini - Bandung Institute of Technology, Indonesia
"""

"""
Receiver Trasped 16C
Channel 1: throttle
Channel 2: steering
Channel 6: save
Channel 7: mode
Channel 11: command
"""

import os
import shutil
import time
import math
import numpy as np
import pandas as pd
import cv2
import argparse
import serial
import Adafruit_PCA9685
try:
    import pyrealsense2 as rs
except ImportError:
    print("No module named pyrealsense2")
import tensorflow as tf
import tensorflow.keras.backend as K
try:
    from train import rmse, get_lr_metric
except ImportError:
    print("train modules cannot be imported")
from tensorflow.keras.models import load_model
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'


# DIRECTORY PATH
PARENT_DIR = os.sep.join(os.getcwd().split(os.sep)[:-1])
MODEL_LEFT_PATH = 'models/model_left.h5'
MODEL_STRAIGHT_PATH = 'models/model_straight.h5'
MODEL_RIGHT_PATH = 'models/model_right.h5'
DATASET_PATH = os.path.join(PARENT_DIR, 'dataset/images')
CSV_PATH = os.path.join(PARENT_DIR, 'dataset/dataset.csv')
SAVE_PATH = os.path.join(os.getcwd(), 'test_dataset/images')
TEST_CSV_PATH = os.path.join(os.getcwd(), 'test_dataset/steering_testing.csv')

# PARAMETERS
THROTTLE_TEST = 345
THROTTLE_IDLE = 305
STEERING_IDLE = 300
IMAGE_HEIGHT, IMAGE_WIDTH, IMAGE_CHANNEL = 100, 220, 3
text_params = {'fontFace': cv2.FONT_HERSHEY_SIMPLEX,
               'fontScale': 0.7,
               'color': (0,0,255),
               'thickness': 1,
               'lineType': cv2.LINE_AA}

# VARIABLES
image_filename_list = []
throttle_list = []
steering_list = []


def rmse(y_true, y_pred):
    return K.sqrt(K.mean(K.square(y_pred - y_true), axis=-1))

def get_lr_metric(optimizer):
    def lr(y_true, y_pred):
        return optimizer._decayed_lr(tf.float32)
    return lr

def pulse_to_bit(pulse):
    """
    Trasped-16C controller sends 50 Hz signal to receiver
    Convert pulseIn reading from Arduino to 12-bit-scale pulse length
    Then the pulse length info will be sent to PCA9685
    PCA9685 is sending 12-bit pwm (4096 steps)
    """
    duty_cycle = pulse/20000
    return int(duty_cycle*4095)

def pulse_to_mode(pulse):
    mode = None
    if pulse < 1400: # bottom
        mode = 'manual'
    elif 1400 < pulse < 1600:
        mode = 'neutral'
    elif pulse > 1600:
        mode = 'autonomous'

    return mode

def pulse_to_cmd(pulse):
    command = None
    if pulse < 1400: # bottom
        command = 'left'
    elif 1400 < pulse < 1600:
        command = 'straight'
    elif pulse > 1600:
        command = 'right'

    return command

def pulse_to_save(pulse):
    save = None
    if pulse < 1400:  # bottom
        save = 'yes'
    elif 1400 < pulse < 1600:
        save = 'no'
    elif pulse > 1600:
        save = 'no'

    return save

def normalize(pwm):
    # Convert 12-bit pwm value to [-1,1]
    MIN_STEERING = 203  # right
    MAX_STEERING = 407  # left
    MIN_THROTTLE = 177  # reverse
    MAX_THROTTLE = 432  # forward
    pwm = (MIN_STEERING-pwm)/((MAX_STEERING-MIN_STEERING)/2) + 1

    return pwm

def denormalize(pwm):
    # Convert [-1,1]-value pwm to 12-bit format
    MAX_BIT = 407  # left
    MIN_BIT = 203  # right
    MIN_THROTTLE = 177  # reverse
    MAX_THROTTLE = 432  # forward
    pwm = MAX_BIT - (pwm + 1)/2 * (MAX_BIT - MIN_BIT)

    return int(pwm)

def preprocess(img):
    img = img[70:,:,:]
    img = cv2.resize(img, (IMAGE_WIDTH,IMAGE_HEIGHT))
    img = cv2.cvtColor(img, cv2.COLOR_BGR2YUV)
    img = img/255

    return img

def load_actual(csv_path):
    columns = ['filename', 'throttle', 'steering', 'command']
    dataset = pd.read_csv(csv_path, names=columns, header=0)

    return dataset


# Executing in graph mode
@tf.function
def predict(input_tensor, model):
    return model(input_tensor)


def main_camera(arduino, camera):
    model_left = load_model(MODEL_LEFT_PATH, custom_objects={'rmse': rmse, 'lr': get_lr_metric})
    model_straight = load_model(MODEL_STRAIGHT_PATH, custom_objects={'rmse': rmse, 'lr': get_lr_metric})
    model_right = load_model(MODEL_RIGHT_PATH, custom_objects={'rmse': rmse, 'lr': get_lr_metric})
    count = 0

    # Trigerring forward propagation
    image_test = np.random.uniform(size=(100, 220, 3))
    image_test = np.reshape(image_test, (1, 100, 220, 3))
    predict(image_test, model_left)
    predict(image_test, model_straight)
    predict(image_test, model_right)

    # Remove last saved dataset folder
    if os.path.exists(SAVE_PATH):
        shutil.rmtree(SAVE_PATH)
    os.makedirs(SAVE_PATH)
    # read 5 first line from Arduino to prevent error
    for i in range(5):
        if arduino.in_waiting > 0:
            line = arduino.readline().decode('utf-8').rstrip()
        else:
            continue
    arduino.reset_input_buffer()

    while True:
        if arduino.in_waiting > 0:
            line = arduino.readline().decode('utf-8').rstrip()
            # throttle = pulse_to_bit(int(line.split(',')[0]))
            # steering = pulse_to_bit(int(line.split(',')[1]))
            # mode = pulse_to_mode(int(line.split(',')[2]))
            # command = pulse_to_cmd(int(line.split(',')[3]))
            # save = pulse_to_save(int(line.split(',')[4]))

            # Without throttle and save reading
            throttle = THROTTLE_IDLE
            steering = pulse_to_bit(int(line.split(',')[0]))
            mode = pulse_to_mode(int(line.split(',')[1]))
            command = pulse_to_cmd(int(line.split(',')[2]))
            save = None
        else:
            continue

        # Wait for a color frame
        frames = camera.wait_for_frames()
        color_frame = frames.get_color_frame()
        if not color_frame:
            continue
        # Convert images to numpy arrays
        color_image = np.asanyarray(color_frame.get_data())

        # Mode switching
        if mode == 'manual':
            pca9685.set_pwm(THROTTLE_CHANNEL, 0, throttle)
            pca9685.set_pwm(STEERING_CHANNEL, 0, steering)

        elif mode == 'neutral':
            throttle = THROTTLE_IDLE
            pca9685.set_pwm(THROTTLE_CHANNEL, 0, throttle)
            pca9685.set_pwm(STEERING_CHANNEL, 0, steering)

        elif mode == 'autonomous':
            image_test = preprocess(color_image)
            image_test = np.reshape(image_test, (1, 100, 220, 3))

            # Predict
            if command == 'left':
                steering_pred = float(predict(image_test, model_left))
            elif command == 'straight':
                steering_pred = float(predict(image_test, model_straight))
            elif command == 'right':
                steering_pred = float(predict(image_test, model_right))
            throttle = THROTTLE_TEST
            steering = denormalize(steering_pred)
            pca9685.set_pwm(THROTTLE_CHANNEL, 0, throttle)
            pca9685.set_pwm(STEERING_CHANNEL, 0, steering)


        # Saving test data
        if save == 'yes':
            count += 1
            image_filename = '{:05d}.jpg'.format(count)
            image_filename_list.append(image_filename)
            throttle_list.append(throttle)
            steering_list.append(steering)
            cv2.imwrite(SAVE_PATH + '/' + image_filename, color_image)

        # Remove all buffer in serial port
        arduino.reset_input_buffer()

        # Show camera frames
        cv2.imshow('Camera', color_image)
        if cv2.waitKey(1) & 0xFF == 27:
            break

    # Stop system
    camera.stop()
    arduino.close()
    cv2.destroyAllWindows()


if __name__ == '__main__':
    # Initialize Arduino using port /dev/ttyACM0 or static name
    arduino = serial.Serial('/dev/ArduinoNano', 9600, timeout=1)
    arduino.reset_input_buffer()

    # Initialize the PCA9685 using the default address (0x40).
    # There are 2 I2C bus number in Jetson TX2, we're using the 1st bus here
    pca9685 = Adafruit_PCA9685.PCA9685(address=0x40, busnum=1)
    THROTTLE_CHANNEL = 0
    STEERING_CHANNEL = 1
    GEAR_CHANNEL = 3
    # Set frequency to 50hz, because frequency from receiver is 50 Hz.
    pca9685.set_pwm_freq(50)

    # Configure camera depth and color streams
    wC, hC = (640, 360)
    pipeline = rs.pipeline()
    config = rs.config()
    config.enable_stream(rs.stream.color, wC, hC, rs.format.bgr8, 30)
    # Start streaming
    pipeline.start(config)

    # Start main script
    main_camera(arduino, pipeline)

    if len(image_filename_list) > 0:
        # Save testing dataset to csv file
        print("Saving testing data")
        if os.path.exists(TEST_CSV_PATH):
            os.remove(TEST_CSV_PATH)
        columns = ['filename', 'throttle', 'steering']
        dataset_dict = {'filename': image_filename_list,
                        'throttle': throttle_list,
                        'steering': steering_list}
        dataset = pd.DataFrame(dataset_dict)
        dataset.to_csv(TEST_CSV_PATH, index=False, columns=columns)
        print("Done")

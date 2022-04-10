#!/bin/bash
# Script to bind 9 DoF Razor IMU under a static name
# author : nelsoonc - Mechanical Engineering 2017

# Reference: https://unix.stackexchange.com/questions/66901/how-to-bind-usb-device-under-a-static-name

RULES_DIR=/etc/udev/rules.d/99-usb-serial.rules
# VARIABLE TO BE CONFIGURED
# udevadm info -a -p  $(udevadm info -q path -n /dev/ttyUSB0)
NAME=9DoFRazorIMU
SUBSYSTEM=tty
idVendor=1b4f
idProduct=9dof
username=$whoami

# Allowing system to upload code to arduino
sudo usermode -a -G dialout $username

sudo sh -c "echo 'SUBSYSTEM==\"$SUBSYSTEM\", ATTRS{idVendor}==\"$idVendor\", ATTRS{idProduct}==\"$idProduct\", SYMLINK+=\"$NAME\"' >> $RULES_DIR"
sudo udevadm trigger
sleep 2
if [ -e /dev/$NAME ] ; then
  echo "Done binding your IMU under a static name"
  echo "Use ls /dev to check your IMU name, it should be: ${NAME}"
else
  echo "Something's wrong"
  echo "Try to check the issues"
fi
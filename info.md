# Home Assistant integration for NAD receivers

![Python][python-shield]
[![GitHub Release][releases-shield]][releases]
[![Licence][license-shield]][license]
[![Home Assistant][homeassistant-shield]][homeassistant]
[![HACS][hacs-shield]][hacs]  


## Introduction

Home Assistant integration to control NAD receivers over Network or serial.
This is a fork from https://github.com/rrooggiieerr/homeassistant-nad and is altered to use push instead of polling.
Only Power, Source and Volume ist implemented in this fork, hence NAD-simple

## Features

- Installation/Configuration through Config Flow UI
- Power, Source and Volume Feedback is picked up imedeatly becouse of push notifications from NAD

## Adding a new NAD receiver

- After restarting go to **Settings** then **Devices & Services**
- Select **+ Add integration** and type in *NAD-simple*
- Select the *Serial* or *Telnet* and enter the connection details
- Select **Submit**

When your wiring or IP Address is right, a new NAD receiver integration and device will now
be added to your Integrations view. Otherwise you will get a *Failed to connect* error message.
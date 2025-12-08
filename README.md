# Home Assistant integration for NAD receivers

![Python][python-shield]
[![GitHub Release][releases-shield]][releases]
[![Licence][license-shield]][license]
[![Maintainer][maintainer-shield]][maintainer]
[![Home Assistant][homeassistant-shield]][homeassistant]
[![HACS][hacs-shield]][hacs]  

## Introduction

Home Assistant integration to control NAD receivers over Network or serial.
This is a fork from https://github.com/rrooggiieerr/homeassistant-nad and is altered to use push instead of polling.
Only Power, Source and Volume ist implemented in this fork, hence NAD-simple
Thank you rrooggiieerr for your work and inspiration.

## Features

- Installation/Configuration through Config Flow UI
- Power, Source and Volume Feedback is picked up imedeatly becouse of push notifications from NAD

## Installation

### HACS

The recommended way to install this Home Assistant integration is by using [HACS][hacs].
Click the following button to open the integration directly on the HACS integration page.

[![Install NAD-simple from HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=nett.media&repository=ha-nad-simple&category=integration)


### Manually

- Copy the `custom_components/nad-simple` directory of this repository into the
`config/custom_components/` directory of your Home Assistant installation
- Restart Home Assistant

## Adding a new NAD receiver

- After restarting go to **Settings** then **Devices & Services**
- Select **+ Add integration** and type in *NAD-simple*
- Select the *Serial* or *Telnet* Option and enter the connection details
- Select **Submit**

When your wiring or IP Address is right, a new NAD receiver integration and device will now
be added to your Integrations view. Otherwise you will get a *Failed to connect* error message.


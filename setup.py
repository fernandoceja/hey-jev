"""Build the app bundle in alias mode, it runs the code straight from this folder: python setup.py py2app -A"""
from setuptools import setup

APP_NAME = "Hey Jev - Fish Audio"

setup(
    name=APP_NAME,
    app=["app.py"],
    options={"py2app": {
        "argv_emulation": False,
        "iconfile": "assets/icon.icns",
        "plist": {
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": APP_NAME,
            "CFBundleIdentifier": "com.heyjev.app",
            "CFBundleShortVersionString": "0.3",
            "LSUIElement": False,
            "NSHighResolutionCapable": True,
            "NSMicrophoneUsageDescription": "Hey Jev listens for your commands.",
            "NSAppleEventsUsageDescription": "Hey Jev controls Music, volume, brightness, Accessibility, Focus, Reminders, Notes, Mail, ChatGPT, and shortcuts in the Jev folder.",
            "NSCalendarsFullAccessUsageDescription": "Hey Jev reads your calendar to answer what's next, today's events, your next shift, the morning brief, Zoe's day, and when to leave for a shift.",
            "NSCalendarsUsageDescription": "Hey Jev reads your calendar to answer what's next, today's events, your next shift, the morning brief, Zoe's day, and when to leave for a shift.",
        },
    }},
    setup_requires=["py2app"],
)

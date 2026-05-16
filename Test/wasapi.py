import sounddevice as sd

for i, api in enumerate(sd.query_hostapis()):
    print(f"API {i}: {api['name']}")

print()
for i, dev in enumerate(sd.query_devices()):
    print(f"[{i}] {dev['name']}  in:{dev['max_input_channels']} out:{dev['max_output_channels']}  api:{dev['hostapi']}")
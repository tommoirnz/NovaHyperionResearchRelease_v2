import pythoncom, win32com.client
pythoncom.CoInitialize()
sp = win32com.client.Dispatch("SAPI.SpVoice")
vs = sp.GetVoices()
for i in range(vs.Count):
    print(repr(vs.Item(i).GetDescription()))
pythoncom.CoUninitialize()
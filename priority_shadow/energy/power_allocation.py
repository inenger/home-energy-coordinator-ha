"""Shared instantaneous AC allocation, never a device command or pulse estimate."""
import math


def allocate_power(room_w,battery_request_w,ev_request_w,min_ev_w,priority,quantum_w=100.):
    room=max(0.,room_w);request=max(0.,battery_request_w);ev_request=max(0.,ev_request_w)
    first_battery=priority=='battery'
    battery=min(room,request) if first_battery else 0.
    if first_battery and quantum_w:battery=math.floor((battery+1e-8)/quantum_w)*quantum_w
    ev=min(ev_request,max(0.,room-battery))
    if 0<ev<min_ev_w-1e-8:ev=0.
    if not first_battery:battery=min(request,max(0.,room-ev))
    if quantum_w:battery=math.floor((battery+1e-8)/quantum_w)*quantum_w
    return battery,ev

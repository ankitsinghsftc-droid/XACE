extends SceneTree
var tcp := StreamPeerTCP.new()
var deadline := 0
func _initialize() -> void:
    deadline=Time.get_ticks_msec()+8000
    tcp.connect_to_host("1.1.1.1",443)
func _process(_delta: float) -> bool:
    tcp.poll()
    var connected := tcp.get_status()==StreamPeerTCP.STATUS_CONNECTED
    if connected or Time.get_ticks_msec()>deadline:
        var output=OS.get_cmdline_user_args()[0]
        FileAccess.open(output,FileAccess.WRITE).store_string(JSON.stringify({"schema":"xace.nec016.network_probe.v1","connected":connected,"endpoint":"1.1.1.1:443","pid":OS.get_process_id()}))
        tcp.disconnect_from_host()
        quit(0)
    return false

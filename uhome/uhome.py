import time
import json

class Device:

    _mqttc = None # MQTT Client, provided by the user.
    _entities = [] # List of entities that belong to this device.

    def __init__(self, device_name, discovery_prefix='homeassistant', **kwargs):
        self.name = device_name
        self.id = self.name.replace(' ', '_').lower()
        self.discovery_prefix = discovery_prefix
        self.will_topic = f'{self.discovery_prefix}/availability/{self.id}'
        self.device = kwargs
        self.device['name'] = self.name
        self.device['ids'] = self.id

    def connect(self, mqttc):
        self._mqttc = mqttc
        self.ping_interval = int(self._mqttc.keepalive * 0.8)
        self._last_ping = time.time()
        self._mqttc.set_last_will(self.will_topic, 'offline', retain=True)
        self._mqttc.set_callback(self.mqtt_callback)
        self._mqttc.connect()
        self._mqttc.publish(self.will_topic, 'online', retain=True)

    def mqtt_callback(self, topic, msg):
        for entity in self._entities:
            if topic.decode() == entity.topic:
                entity._action(msg.decode())

    def loop(self):
        ### Broker ping (required for Mosquitto >= 2.0!)
        now = time.time()
        if (now - self._last_ping) > self.ping_interval:
            self._mqttc.ping()
            self._last_ping = now
        
        self._mqttc.check_msg() # Check for new MQTT messages

    def discover_all(self):
        for entity in self._entities:
            entity.discover()

class Entity(Device):

    def __init__(self, device, entity_name, **kwargs):
        self.device = device
        self.device._entities.append(self)
        self.name = entity_name
        self.entity = entity_name.replace(' ', '_').lower()
        self.unique_id = f"{self.device.id}_{self.entity}"
        self.topic_prefix = f'{self.device.discovery_prefix}/{self.entity_type}/{self.device.id}'
        self.discovery_topic = f'{self.topic_prefix}/{self.entity}/config'
        self.topic = f'{self.topic_prefix}/state/{self.entity}'
        self.conf = self.make_conf(**kwargs)

    def make_conf(self, **kwargs):
        conf = {
            "name":self.name,
            "dev":self.device.device,
            "uniq_id":self.unique_id,
            "avty_t":self.device._mqttc.lw_topic, # Availability topic
        }
        if self.entity_type == 'sensor':
            conf["stat_t"] = self.topic # State topic
        elif self.entity_type == 'button':
            conf["cmd_t"] = self.topic # Command topic
        for arg in kwargs:
            conf[arg] = kwargs[arg]
        return conf
    
    def discover(self):
        self.device._mqttc.publish(self.discovery_topic, json.dumps(self.conf).encode('utf-8'))

class Sensor(Entity):

    entity_type = 'sensor'
    _last_payload = None
    
    def publish(self, payload):
        payload = str(payload)
        if payload == self._last_payload: return
        self.device._mqttc.publish(f'{self.conf['stat_t']}', payload)
        self._last_payload = payload

class Button(Entity):

    entity_type = 'button'
    _action = None

    def get_topic(self):
        return self.conf['cmd_t']
    
    def set_action(self, action):
        """
        Set the action to be performed when the button is pressed.
        Action needs to take one argument, the message received.
        """
        self.device._mqttc.subscribe(self.conf['cmd_t'])
        self._action = action
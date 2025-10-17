from .mixins.util import UtilMixin
from .mixins.mqtt import MqttMixin
from .mixins.topics import TopicsMixin
from .mixins.service import ServiceMixin
from .mixins.govee import GoveeMixin
from .mixins.govee_api import GoveeAPIMixin
from .mixins.refresh import RefreshMixin
from .mixins.helpers import HelpersMixin
from .mixins.loops import LoopsMixin
from .base import Base


class Govee2Mqtt(
    UtilMixin,
    TopicsMixin,
    ServiceMixin,
    GoveeMixin,
    GoveeAPIMixin,
    RefreshMixin,
    HelpersMixin,
    LoopsMixin,
    MqttMixin,
    Base,
):
    pass

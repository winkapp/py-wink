import requests
import json
from pprint import pprint

from auth import reauth, need_to_reauth
import devices


class Wink(object):
    """Main object for making API calls to the Wink cloud servers.

    Constructor requires a persistence object,
    e.g. persist.ConfigFile.

    "populate_devices" reads the device list from the Wink servers
    and instantiates the appropriate class for each device.

    There are several ways to access the device objects:
    "device_list" gives the full list of top-level devices
    "devices_by_type" gives all devices of a given type
    "device_types" gives all device types that are instantiated
    "[device_type]" returns the device object for the first seen
        for the given type
    "[device_type]s" returns a list of all devices of that type
    """

    content_headers = {
        "Content-Type": "application/json",
    }

    def __init__(self, auth_object, save_auth=True, debug=False):
        """
        Provide an object from the persist module, which will be used
        to load and save authentication tokens as needed.
        """

        self.debug = debug

        if save_auth:
            self.auth_object = auth_object
            self.auth = self.auth_object.load()
        else:
            self.auth = auth_object
            self.auth_object = None


    def _url(self, path, base_url=None):
        base_url = base_url if base_url is not None else self.auth["base_url"]
        return "%s%s" % (base_url, path)

    def _headers(self):
        return {
            "Authorization": "Bearer %s" % self.auth["access_token"],
            "User-Agent": "wink/99.99.99 (iPhone; iOS 7.1.2; Scale/2.0)"
        }

    def _http(self, path, method, headers={}, body=None, expected="200", base_url=None):
        # see if we need to reauth?
        if need_to_reauth(**self.auth):
            if self.debug:
                print "Refreshing access token"

            # TODO add error handling
            self.auth = reauth(**self.auth)

            if self.auth_object is not None:
                self.auth_object.save(self.auth)

        # add the auth header
        all_headers = self._headers()
        all_headers.update(headers)

        if body:
            all_headers.update(Wink.content_headers)
            if type(body) is not str:
                body = json.dumps(body)

        if self.debug:
            print "Request: %s %s" % (method, path)
            if headers:
                print "Extra headers:", headers
            if body:
                print "Body:",
                pprint(body)

        url = self._url(path, base_url=base_url)

        if method == "GET":
            response = requests.get(url, data=body, headers=all_headers)
        elif method == "PUT":
            response = requests.put(url, data=body, headers=all_headers)
        elif method == "POST":
            response = requests.post(url, data=body, headers=all_headers)
        elif method == "DELETE":
            response = requests.delete(url, data=body, headers=all_headers)

        content = response.content

        if self.debug:
            print "Response:", str(response.status_code)

        # coerce to JSON, if possible
        if content:
            try:
                content = json.loads(content)
                if "errors" in content and content["errors"]:
                    raise RuntimeError("\n".join(content["errors"]))
            except:
                pass

        if self.debug:
            pprint(content)

        if type(expected) is str:
            expected = set([expected])

        if str(response.status_code) not in expected:
            raise RuntimeError(
                "expected code %s, but got %s for %s %s" % (
                    expected,
                    str(response.status_code),
                    method,
                    path,
                )
            )

        if content:
            return content
        return {}

    def _get(self, path, base_url=None):
        return self._http(path, "GET", base_url=base_url).get("data")

    def _put(self, path, data, base_url=None):
        return self._http(path, "PUT", body=data, expected=["200", "201", "202", "204"], base_url=base_url).get("data")

    def _post(self, path, data, base_url=None):
        return self._http(path, "POST", body=data,
                          expected=["200", "201", "202", "204"], base_url=base_url).get("data")

    def _delete(self, path, base_url=None):
        return self._http(path, "DELETE", expected="204", base_url=base_url)

    def get_profile(self):
        return self._get("/users/me")

    def update_profile(self, data):
        return self._put("/users/me", data)

    def update_profile_email(self, email):
        return self.update_profile(dict(email=email))

    def get_devices(self):
        return self._get("/users/me/wink_devices")

    def get_geofences(self):
        return self._get("/users/me/geofences")

    def get_services(self):
        return self._get("/users/me/linked_services")

    def create_service(self, data):
        return self._post("/users/me/linked_services", data)

    def get_icons(self):
        return self._get("/icons")

    def get_channels(self):
        return self._get("/channels")

    def get_inbound_channels(self):
        return [x for x in self.get_channels() if x["inbound"]]

    def get_outbound_channels(self):
        return [x for x in self.get_channels() if x["outbound"]]

    def populate_devices(self):
        devices_info = self.get_devices()

        # clean up data structures, just in case this is called
        # multiple times in the same instance.
        del self._device_list[:]
        for device_type in self._devices_by_type:
            delattr(self, device_type)
            delattr(self, "%ss" % device_type)
        self._devices_by_type.clear()

        for device_info in devices_info:
            device_type = None
            for k in device_info:
                if k.endswith("_id") and hasattr(devices, k[:-3]):
                    device_type = k[:-3]
                    break

            if device_type is None:
                continue

            device_cls = getattr(devices, device_type)
            device_obj = device_cls(self, device_info)

            # update some data structures to provide access to the devices
            self._device_list.append(device_obj)

            if not hasattr(self, device_type):
                setattr(self,
                        device_type,
                        self._get_device_func(device_obj))
                self._devices_by_type[device_type] = []
                setattr(self,
                        "%ss" % device_type,
                        self._get_device_list_func(device_type))

            self._devices_by_type[device_type].append(device_obj)

    def _get_device_func(self, device_object):
        return lambda: device_object

    def _get_device_list_func(self, device_type):
        return lambda: list(self._devices_by_type[device_type])

    def device_list(self):
        return list(self._device_list)

    def device_types(self):
        return list(self._devices_by_type)

    def devices_by_type(self, typ):
        return list(self._devices_by_type.get(typ, []))

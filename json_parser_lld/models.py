from typing import Any, Dict, List, Union

class JsonValue:
    """
    Base class for all JSON values.
    """
    def to_native(self) -> Any:
        """
        Converts the JsonValue instance to its native Python representation.
        """
        raise NotImplementedError

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, JsonValue):
            return NotImplemented
        return self.to_native() == other.to_native()

    def __ne__(self, other: object) -> bool:
        return not self.__eq__(other)

    def __hash__(self) -> int:
        return hash(self.to_native())

class JsonString(JsonValue):
    """
    Represents a JSON string.
    """
    def __init__(self, value: str):
        self._value = value

    def to_native(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return f'JsonString("{self._value}")'

class JsonNumber(JsonValue):
    """
    Represents a JSON number (integer or float).
    """
    def __init__(self, value: Union[int, float]):
        self._value = value

    def to_native(self) -> Union[int, float]:
        return self._value

    def __repr__(self) -> str:
        return f'JsonNumber({self._value})'

class JsonBoolean(JsonValue):
    """
    Represents a JSON boolean (true or false).
    """
    def __init__(self, value: bool):
        self._value = value

    def to_native(self) -> bool:
        return self._value

    def __repr__(self) -> str:
        return f'JsonBoolean({self._value})'

class JsonNull(JsonValue):
    """
    Represents a JSON null.
    """
    def __init__(self):
        self._value = None

    def to_native(self) -> None:
        return self._value

    def __repr__(self) -> str:
        return f'JsonNull()'

# Singleton for JsonNull to ensure only one instance
JSON_NULL = JsonNull()

class JsonArray(JsonValue):
    """
    Represents a JSON array.
    """
    def __init__(self, values: List[JsonValue]):
        self._values = values

    def to_native(self) -> List[Any]:
        return [value.to_native() for value in self._values]

    def __repr__(self) -> str:
        return f'JsonArray({self._values})'

    def __len__(self) -> int:
        return len(self._values)

    def __getitem__(self, key: int) -> JsonValue:
        return self._values[key]

class JsonObject(JsonValue):
    """
    Represents a JSON object.
    """
    def __init__(self, properties: Dict[str, JsonValue]):
        self._properties = properties

    def to_native(self) -> Dict[str, Any]:
        return {key: value.to_native() for key, value in self._properties.items()}

    def __repr__(self) -> str:
        return f'JsonObject({self._properties})'

    def __len__(self) -> int:
        return len(self._properties)

    def __getitem__(self, key: str) -> JsonValue:
        return self._properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self._properties
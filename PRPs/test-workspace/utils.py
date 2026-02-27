def add(a, b):
    """Add two numbers and return the result.

    Args:
        a: First number (int or float)
        b: Second number (int or float)

    Returns:
        The sum of a and b

    Raises:
        TypeError: If either argument is not a number
    """
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        raise TypeError(f"Both arguments must be numbers, got {type(a).__name__} and {type(b).__name__}")
    return a + b


def multiply(a, b):
    """Multiply two numbers and return the result.

    Args:
        a: First number (int or float)
        b: Second number (int or float)

    Returns:
        The product of a and b

    Raises:
        TypeError: If either argument is not a number
    """
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        raise TypeError(f"Both arguments must be numbers, got {type(a).__name__} and {type(b).__name__}")
    return a * b

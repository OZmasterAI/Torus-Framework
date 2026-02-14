"""Pytest tests for utils module."""
import pytest
from utils import add, multiply


class TestAdd:
    """Test suite for add function."""

    def test_add_positive_numbers(self):
        """Test adding two positive numbers."""
        assert add(2, 3) == 5
        assert add(10, 20) == 30

    def test_add_negative_numbers(self):
        """Test adding two negative numbers."""
        assert add(-5, -3) == -8
        assert add(-10, -20) == -30

    def test_add_mixed_numbers(self):
        """Test adding positive and negative numbers."""
        assert add(10, -5) == 5
        assert add(-10, 5) == -5

    def test_add_zero(self):
        """Test adding with zero."""
        assert add(0, 0) == 0
        assert add(5, 0) == 5
        assert add(0, 5) == 5

    def test_add_floats(self):
        """Test adding floating point numbers."""
        assert add(2.5, 3.5) == 6.0
        assert add(1.1, 2.2) == pytest.approx(3.3)


class TestMultiply:
    """Test suite for multiply function."""

    def test_multiply_positive_numbers(self):
        """Test multiplying two positive numbers."""
        assert multiply(2, 3) == 6
        assert multiply(10, 5) == 50

    def test_multiply_negative_numbers(self):
        """Test multiplying two negative numbers."""
        assert multiply(-5, -3) == 15
        assert multiply(-10, -2) == 20

    def test_multiply_mixed_numbers(self):
        """Test multiplying positive and negative numbers."""
        assert multiply(10, -5) == -50
        assert multiply(-10, 5) == -50

    def test_multiply_by_zero(self):
        """Test multiplying by zero."""
        assert multiply(0, 0) == 0
        assert multiply(5, 0) == 0
        assert multiply(0, 5) == 0

    def test_multiply_by_one(self):
        """Test multiplying by one."""
        assert multiply(5, 1) == 5
        assert multiply(1, 5) == 5

    def test_multiply_floats(self):
        """Test multiplying floating point numbers."""
        assert multiply(2.5, 2.0) == 5.0
        assert multiply(1.5, 2.0) == pytest.approx(3.0)

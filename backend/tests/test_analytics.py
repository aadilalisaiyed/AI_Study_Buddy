from datetime import date

from app.services.analytics_service import ratio, streaks


def test_undefined_rates_and_partial_marks():
    assert ratio(0, 0) is None
    assert ratio(0, 3) == 0
    assert ratio(1, 3) == 33.33


def test_streak_crosses_leap_day_and_accepts_yesterday():
    days = [date(2024, 2, 28), date(2024, 2, 29), date(2024, 2, 29), date(2024, 3, 1)]
    assert streaks(days, date(2024, 3, 2)) == (3, 3)
    assert streaks(days, date(2024, 3, 3)) == (0, 3)
    assert streaks([], date(2024, 3, 3)) == (0, 0)

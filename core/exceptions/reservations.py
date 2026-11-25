from core.exceptions import BaseAppException


class ReservationNotFoundException(BaseAppException):
    status_code = 404
    code = "reservation_not_found"
    message = "Reservation not found."


class ReservationsDisabledException(BaseAppException):
    status_code = 400
    code = "reservations_disabled"
    message = "Reservations are not enabled for this branch."


class InvalidReservationStatusTransitionException(BaseAppException):
    status_code = 400
    code = "invalid_reservation_status_transition"
    message = "This reservation status transition is not allowed."


class ReservationNotCancellableException(BaseAppException):
    status_code = 400
    code = "reservation_not_cancellable"
    message = "Reservation can no longer be cancelled."


class ReservationAlreadyCancelledException(BaseAppException):
    status_code = 400
    code = "reservation_already_cancelled"
    message = "Reservation is already cancelled."


class ReservationTimeUnavailableException(BaseAppException):
    status_code = 400
    code = "reservation_time_unavailable"
    message = "This time is not available. Please choose another one."


class ReservationAlreadyBookedException(BaseAppException):
    status_code = 400
    code = "reservation_already_booked"
    message = "You already have a reservation here around this time."


class ReservationDurationUnavailableException(BaseAppException):
    status_code = 400
    code = "reservation_duration_unavailable"
    message = "The time after this reservation is not free that long."


class ReservationNotAdjustableException(BaseAppException):
    status_code = 400
    code = "reservation_not_adjustable"
    message = "The length of a finished or cancelled reservation cannot change."


class PartySizeExceedsCapacityException(BaseAppException):
    status_code = 400
    code = "party_size_exceeds_capacity"
    message = "Party size exceeds this branch's maximum capacity."

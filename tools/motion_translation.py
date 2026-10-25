"""Experimental short-swipe inertial displacement, NOT absolute position tracking.

An MPU cannot distinguish rest from constant velocity. Rest detection, filtering,
velocity leakage and bounds deliberately trade physical accuracy for usable short
cursor swipes. Slow translation can be missed; gravity/bias errors still drift.
"""
import math


def rotate_vector(q, vector):
    w, x, y, z = q
    a, b, c = vector
    return ((1-2*(y*y+z*z))*a + 2*(x*y-w*z)*b + 2*(x*z+w*y)*c,
            2*(x*y+w*z)*a + (1-2*(x*x+z*z))*b + 2*(y*z-w*x)*c,
            2*(x*z-w*y)*a + 2*(y*z+w*x)*b + (1-2*(x*x+y*y))*c)


def horizontal_axis(q, axis=0):
    basis = rotate_vector(q, (1, 0, 0) if axis == 0 else (0, 1, 0))
    length = math.hypot(basis[0], basis[1])
    if length < .2:
        raise ValueError('Selected sideways axis is vertical. Lower the hand or select the other axis.')
    return (basis[0]/length, basis[1]/length, 0.0)


class InertialTranslation:
    def __init__(self):
        self.reset()

    def reset(self):
        self.position = [0.0] * 3
        self.velocity = [0.0] * 3
        self.filtered = [0.0] * 3
        self.bias = [0.0] * 3
        self.ready = self.stationary = False
        self.still_time = 0.0
        self.warm_count = 0
        self.warm_mean = [0.0] * 3
        self.warm_m2 = [0.0] * 3

    def update(self, values, q, gyro_bias=(0, 0, 0), dt=.001):
        if q is None or not 0 < dt <= .02 or not all(math.isfinite(v) for v in (*values, *q)):
            self.reset()
            return
        world = rotate_vector(q, values[:3])
        residual = (world[0], world[1], world[2]-1.0)
        rotation = math.sqrt(sum((g-b)**2 for g, b in zip(values[3:], gyro_bias)))
        norm = math.sqrt(sum(a*a for a in values[:3]))
        if not self.ready:
            if rotation > 4 or not .85 < norm < 1.15:
                self.warm_count = 0
                self.warm_mean = [0.0] * 3
                self.warm_m2 = [0.0] * 3
                return
            self.warm_count += 1
            for i in range(3):
                delta = residual[i] - self.warm_mean[i]
                self.warm_mean[i] += delta / self.warm_count
                self.warm_m2[i] += delta * (residual[i] - self.warm_mean[i])
            if self.warm_count * dt >= .6:
                if max(self.warm_m2) / self.warm_count < .0001:
                    self.bias = self.warm_mean[:]
                    self.ready = self.stationary = True
                else:
                    self.warm_count = 0
                    self.warm_mean = [0.0] * 3
                    self.warm_m2 = [0.0] * 3
            return
        blend = -math.expm1(-dt / .05)
        for i in range(3):
            self.filtered[i] += blend * (residual[i] - self.bias[i] - self.filtered[i])
        quiet = math.sqrt(sum(v*v for v in self.filtered)) < .035 and rotation < 5
        self.still_time = self.still_time + dt if quiet else 0.0
        self.stationary = self.still_time >= .18
        if self.stationary:
            self.velocity = [0.0] * 3
            for i in range(3):
                self.bias[i] += (-math.expm1(-dt / 2)) * (residual[i] - self.bias[i])
            return
        for i in range(2):
            acceleration = math.copysign(max(0, abs(self.filtered[i]) - .025), self.filtered[i]) * 9.80665
            # Short-swipe heuristic: no claim of metrically accurate displacement.
            self.velocity[i] = self.velocity[i] * math.exp(-dt / (.05 if quiet else 1.0)) + acceleration * dt
            self.velocity[i] = max(-.8, min(.8, self.velocity[i]))
            self.position[i] = max(-2.0, min(2.0, self.position[i] + self.velocity[i] * dt))

    def snapshot(self):
        return {'ready': self.ready, 'stationary': self.stationary,
                'position_m': tuple(self.position), 'velocity_mps': tuple(self.velocity),
                'linear_accel_g': tuple(self.filtered), 'approximate': True}


class CursorStabilizer:
    """Two-pole position smoothing and 2 px hysteresis; faster for large moves."""
    def __init__(self):
        self.reset((0, 0))

    def reset(self, point):
        self.first = list(map(float, point))
        self.second = self.first[:]
        self.output = tuple(map(round, point))

    def step(self, target, dt):
        if not 0 < dt <= .1:
            return self.output
        distance = math.hypot(target[0]-self.second[0], target[1]-self.second[1])
        tau = .018 if distance > 80 else .055
        blend = -math.expm1(-dt/tau)
        for i in range(2):
            self.first[i] += blend * (target[i]-self.first[i])
            self.second[i] += blend * (self.first[i]-self.second[i])
        proposed = tuple(round(v) for v in self.second)
        self.output = tuple(proposed[i] if abs(proposed[i]-self.output[i]) > 2 else self.output[i] for i in range(2))
        return self.output

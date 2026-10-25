from engine import GestureEngine
from simulator import make_motion


def test_simulated_known_classes():
    model = GestureEngine()
    for name in ('flick_right', 'flick_left', 'double_twist', 'circle'):
        for seed in range(12):
            model.add(name, make_motion(name, seed))
    model.train()
    for name in ('flick_right', 'flick_left', 'double_twist', 'circle'):
        recognized = sum(model.predict(make_motion(name, seed))['label'] == name
                         for seed in range(100, 108))
        assert recognized >= 6, (name, recognized)


def test_unknown_rejection():
    model = GestureEngine()
    for name in ('flick_right', 'flick_left', 'double_twist', 'circle'):
        for seed in range(10):
            model.add(name, make_motion(name, seed))
    model.train()
    assert model.predict(make_motion('unknown', seed=224))['label'] == 'unknown'

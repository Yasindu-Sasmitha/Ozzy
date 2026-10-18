import 'dart:async';
import 'dart:math';
import 'package:flutter/material.dart';

/// Minimal eyes-only Ozzy face. The gaze drifts on its own and reacts to the
/// current activity and inferred conversational mood.
class OzzyFace extends StatefulWidget {
  const OzzyFace({super.key, required this.state, this.mood = 'neutral', this.onTap});
  final String state;
  final String mood;
  final VoidCallback? onTap;

  @override
  State<OzzyFace> createState() => _OzzyFaceState();
}

class _OzzyFaceState extends State<OzzyFace> {
  final _random = Random();
  Timer? _gazeTimer;
  Timer? _blinkTimer;
  Offset _gaze = Offset.zero;
  bool _blink = false;

  @override
  void initState() {
    super.initState();
    _scheduleGaze();
    _scheduleBlink();
  }

  @override
  void didUpdateWidget(covariant OzzyFace oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.state != widget.state || oldWidget.mood != widget.mood) {
      _scheduleGaze(reschedule: true);
    }
  }

  void _scheduleGaze({bool reschedule = false}) {
    if (reschedule) _gazeTimer?.cancel();
    final state = widget.state;
    final low = state == 'sleepy' || widget.mood == 'sleepy' ? 2600 : (state == 'speaking' ? 1300 : 650);
    final high = state == 'sleepy' || widget.mood == 'sleepy' ? 5200 : (state == 'speaking' ? 3000 : 2400);
    _gazeTimer = Timer(Duration(milliseconds: low + _random.nextInt(high - low + 1)), () {
      if (!mounted) return;
      final magnitude = state == 'visual' ? 18.0 : (state == 'thinking' || widget.mood == 'curious' ? 15.0 : 12.0);
      setState(() {
        _gaze = Offset((_random.nextDouble() * 2 - 1) * magnitude, (_random.nextDouble() * 2 - 1) * magnitude * .62);
      });
      _gazeTimer = Timer(Duration(milliseconds: 360 + _random.nextInt(850)), () {
        if (!mounted) return;
        setState(() => _gaze = Offset.zero);
        _scheduleGaze();
      });
    });
  }

  void _scheduleBlink() {
    _blinkTimer = Timer(Duration(milliseconds: 2300 + _random.nextInt(4800)), () async {
      if (!mounted) return;
      if (widget.state != 'sleepy' && widget.mood != 'sleepy') {
        setState(() => _blink = true);
        await Future<void>.delayed(const Duration(milliseconds: 115));
        if (mounted) setState(() => _blink = false);
        if (_random.nextInt(5) == 0) {
          await Future<void>.delayed(const Duration(milliseconds: 190));
          if (mounted) {
            setState(() => _blink = true);
            await Future<void>.delayed(const Duration(milliseconds: 95));
            if (mounted) setState(() => _blink = false);
          }
        }
      }
      if (mounted) _scheduleBlink();
    });
  }

  @override
  void dispose() {
    _gazeTimer?.cancel();
    _blinkTimer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final state = widget.state;
    final mood = widget.mood;
    final activeMood = (state == 'idle' || state == 'listening') ? mood : state;
    final isHappy = activeMood == 'happy' || activeMood == 'excited';
    final isSleepy = activeMood == 'sleepy';
    final isSad = activeMood == 'sad' || activeMood == 'concerned';
    final isSurprised = activeMood == 'surprised';
    final isCurious = activeMood == 'curious' || state == 'thinking';
    final isAnnoyed = activeMood == 'annoyed' || activeMood == 'confused';
    final isLove = activeMood == 'affection';
    final isError = state == 'error';
    final baseW = min(MediaQuery.sizeOf(context).width * .23, 78.0).clamp(54.0, 78.0).toDouble();
    final baseH = baseW * .99;
    final eyeW = isLove ? baseW * .9 : baseW;
    final eyeH = _blink ? 4.0 : isSleepy ? baseH * .38 : isHappy ? baseH * .67 : isSurprised ? baseH * 1.13 : isSad ? baseH * .83 : baseH;
    final radius = isSleepy ? 17.0 : (isHappy ? 18.0 : 10.0);
    final glow = isError ? const Color(0xFFFF667A) : const Color(0xFF25CFEF);
    final gap = baseW * .34;

    return GestureDetector(
      onTap: widget.onTap,
      child: SizedBox.expand(
        child: Stack(
          alignment: Alignment.center,
          clipBehavior: Clip.none,
          children: [
            AnimatedContainer(
              duration: const Duration(milliseconds: 350),
              width: baseW * 5.5,
              height: baseH * 3.5,
              decoration: BoxDecoration(shape: BoxShape.circle, color: glow.withValues(alpha: state == 'speaking' ? .045 : .018), boxShadow: [BoxShadow(color: glow.withValues(alpha: state == 'speaking' ? .06 : .025), blurRadius: 65, spreadRadius: 16)]),
            ),
            Transform.translate(
              offset: _gaze,
              child: isLove
                  ? Row(mainAxisSize: MainAxisSize.min, children: [
                      Icon(Icons.favorite_rounded, size: baseW * 1.06, color: glow, shadows: [Shadow(color: glow.withValues(alpha: .42), blurRadius: 24)]),
                      SizedBox(width: gap * .55),
                      Icon(Icons.favorite_rounded, size: baseW * 1.06, color: glow, shadows: [Shadow(color: glow.withValues(alpha: .42), blurRadius: 24)]),
                    ])
                  : Row(
                      mainAxisSize: MainAxisSize.min,
                      crossAxisAlignment: CrossAxisAlignment.center,
                      children: [
                        _eye(width: eyeW, height: eyeH, radius: radius, glow: glow, rotate: isAnnoyed ? -.14 : (isSad ? .08 : (isCurious ? -.05 : 0)), visual: state == 'visual', speaking: state == 'speaking'),
                        SizedBox(width: gap),
                        Transform.translate(
                          offset: Offset(isCurious ? 2 : 0, isCurious ? -baseH * .07 : 0),
                          child: _eye(width: eyeW, height: isCurious ? eyeH * .89 : eyeH, radius: radius, glow: glow, rotate: isAnnoyed ? .14 : (isSad ? -.08 : (isCurious ? .055 : 0)), visual: state == 'visual', speaking: state == 'speaking'),
                        ),
                      ],
                    ),
            ),
            if (isCurious && !isSleepy)
              Positioned(
                top: MediaQuery.sizeOf(context).height * .34,
                right: MediaQuery.sizeOf(context).width * .23,
                child: Row(children: [for (int i = 0; i < 3; i++) Transform.rotate(angle: [-.1, .35, .95][i], child: Container(margin: const EdgeInsets.only(left: 7), width: 4, height: 11 + (i == 2 ? -2 : 0), decoration: BoxDecoration(color: glow.withValues(alpha: .8), borderRadius: BorderRadius.circular(4))))]),
              ),
          ],
        ),
      ),
    );
  }

  Widget _eye({required double width, required double height, required double radius, required Color glow, required double rotate, required bool visual, required bool speaking}) {
    return Transform.rotate(
      angle: rotate,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 190),
        curve: Curves.easeOutCubic,
        width: width,
        height: height,
        decoration: BoxDecoration(
          color: glow,
          borderRadius: BorderRadius.circular(radius),
          boxShadow: [
            BoxShadow(color: glow.withValues(alpha: speaking ? .46 : .30), blurRadius: visual ? 31 : 22, spreadRadius: visual ? 2 : 0),
            BoxShadow(color: glow.withValues(alpha: .18), blurRadius: 46, spreadRadius: 9),
          ],
        ),
      ),
    );
  }
}

"""Part 4: find speed signs in dashcam footage that has been saved out as
photos.

The pipeline is deliberately two-staged. A drive of any length produces
thousands of frames, the overwhelming majority of which contain no sign at
all, and paying a vision model to look at each one is the difference between
a few pence and a few pounds per video. So a free local pass
(`prefilter`) scores every frame on the colours and contrasts a speed sign
actually has, and only what survives that goes to Claude (`vision`) to be
identified. `detect` runs the two in order and `report` writes the result
out in a form a chapter can cite.
"""

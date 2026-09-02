document.addEventListener("DOMContentLoaded", function () {
    const canvas = document.getElementById("animation-canvas");
    if (!canvas) return;

    const context = canvas.getContext("2d");

    const frameCount = 83;

    const currentFrame = index => (
        `/static/components/scroll_animation/images/frame_${index.toString().padStart(3, '0')}.png`
    );

    // Preload images to prevent flickering
    const images = [];
    const preloadImages = () => {
        for (let i = 1; i <= frameCount; i++) {
            const img = new Image();
            img.src = currentFrame(i);
            images.push(img);
        }
    };

    // Draw first frame when image loads
    const img = new Image();
    img.onload = function () {
        canvas.width = img.width;
        canvas.height = img.height;
        context.drawImage(img, 0, 0);
    };
    img.src = currentFrame(1);

    const updateImage = index => {
        // Only draw if the image has finished loading
        if (images[index] && images[index].complete) {
            if (canvas.width !== images[index].width) {
                canvas.width = images[index].width;
                canvas.height = images[index].height;
            }
            context.drawImage(images[index], 0, 0);
        }
    }

    window.addEventListener('scroll', () => {
        const wrapper = document.querySelector('.scroll-animation-wrapper');
        if (!wrapper) return;

        // Calculate scroll progress relative to the wrapper section
        const scrollStart = wrapper.offsetTop;
        const scrollEnd = scrollStart + wrapper.offsetHeight - window.innerHeight;
        const scrollPosition = window.scrollY;

        if (scrollPosition >= scrollStart && scrollPosition <= scrollEnd) {
            const maxScrollableHeight = wrapper.offsetHeight - window.innerHeight;
            const scrollFraction = (scrollPosition - scrollStart) / maxScrollableHeight;

            // Calculate which frame to show
            const frameIndex = Math.min(
                frameCount - 1,
                Math.ceil(scrollFraction * frameCount)
            );

            // Calculate dynamic zoom effect
            const startScale = 1.1;
            const endScale = 0.9;
            const currentScale = startScale - (scrollFraction * (startScale - endScale));

            const startY = 0;
            const endY = 0;
            const currentY = startY - (scrollFraction * (startY - endY));

            canvas.style.transform = `scale(${currentScale}) translateY(${currentY}%)`;

            // Draw the current frame
            requestAnimationFrame(() => updateImage(frameIndex));

            // Show text blocks when near the end of the scroll (e.g., > 30%)
            const textBlocks = document.querySelector('.animation-text-blocks');
            if (textBlocks) {
                if (scrollFraction > 0.30) {
                    textBlocks.classList.add('visible');
                } else {
                    textBlocks.classList.remove('visible');
                }
            }
        } else if (scrollPosition < scrollStart) {
            // Reset to initial normal state when scrolled above
            canvas.style.transform = `scale(1.1) translateY(0%)`;
            requestAnimationFrame(() => updateImage(0));
            document.querySelector('.animation-text-blocks')?.classList.remove('visible');
        } else if (scrollPosition > scrollEnd) {
            // Keep it zoomed out when scrolled below
            canvas.style.transform = `scale(0.9) translateY(0%)`;
            requestAnimationFrame(() => updateImage(frameCount - 1));
            document.querySelector('.animation-text-blocks')?.classList.add('visible');
        }
    });

    preloadImages();
});

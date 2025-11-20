const fs = require('fs');
const path = require('path');
const sharp = require('sharp');
const toIco = require('to-ico');

const publicDir = path.join(__dirname, '../public');
const svgPath = path.join(publicDir, 'sphinx.svg');
const sizes = [16, 32, 48, 64, 128, 192, 512];

async function generateFavicons() {
  try {
    const svgBuffer = fs.readFileSync(svgPath);
    
    // Generate PNGs in various sizes
    const pngPromises = sizes.map(async size => {
      const pngBuffer = await sharp(svgBuffer)
        .resize(size, size)
        .png()
        .toBuffer();
      
      const outputPath = path.join(publicDir, `favicon-${size}x${size}.png`);
      fs.writeFileSync(outputPath, pngBuffer);
      console.log(`Generated ${outputPath}`);
      
      return { size, buffer: pngBuffer };
    });
    
    const pngs = await Promise.all(pngPromises);
    
    // Create ICO file from the 16x16, 32x32, and 48x48 PNGs
    const icoBuffers = pngs
      .filter(png => [16, 32, 48].includes(png.size))
      .map(png => png.buffer);
    
    const icoBuffer = await toIco(icoBuffers);
    const icoPath = path.join(publicDir, 'favicon.ico');
    fs.writeFileSync(icoPath, icoBuffer);
    console.log(`Generated ${icoPath}`);
    
    // Create favicon.png (64x64) as the default PNG favicon
    const faviconPng = pngs.find(png => png.size === 64);
    if (faviconPng) {
      const faviconPath = path.join(publicDir, 'favicon.png');
      fs.writeFileSync(faviconPath, faviconPng.buffer);
      console.log(`Generated ${faviconPath}`);
    }
    
    console.log('All favicons generated successfully!');
  } catch (error) {
    console.error('Error generating favicons:', error);
  }
}

generateFavicons();

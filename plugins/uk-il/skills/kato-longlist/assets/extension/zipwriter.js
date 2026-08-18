/* zipwriter.js - a dependency-free streaming ZIP writer.
 *
 * WHY NOT A LIBRARY: shipping a third-party bundle (fflate, JSZip) into an extension that CBRE IT
 * must review means they audit code we did not write. Chrome has had CompressionStream since 103,
 * so the only thing actually missing is ~120 lines of container format. That is a better trade.
 *
 * Entries are written one at a time straight to the sink, so peak memory is one file, not one
 * bundle. Compressed size must be known before the local header is written, so each entry is
 * compressed fully in memory first - fine, because the largest single Kato asset is a brochure of
 * a few MB, while the BUNDLE can be hundreds.
 *
 * No Zip64: guarded explicitly rather than silently producing a corrupt archive.
 */

const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();

function crc32(u8) {
  let c = 0xffffffff;
  for (let i = 0; i < u8.length; i++) c = CRC_TABLE[(c ^ u8[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

async function deflateRaw(u8) {
  const stream = new Blob([u8]).stream().pipeThrough(new CompressionStream('deflate-raw'));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

function dosDateTime(d) {
  const time = (d.getHours() << 11) | (d.getMinutes() << 5) | (d.getSeconds() >> 1);
  const date = ((d.getFullYear() - 1980) << 9) | ((d.getMonth() + 1) << 5) | d.getDate();
  return { time: time & 0xffff, date: date & 0xffff };
}

/** Already-compressed payloads gain nothing from deflate and cost real CPU on a 200-file run. */
const STORE_EXT = /\.(jpe?g|png|gif|webp|avif|pdf|zip|mp4|mov|docx|xlsx|pptx)$/i;

/** Buffer sink for browsers without the File System Access API. */
export class BufferSink {
  constructor() { this.chunks = []; }
  async write(u8) { this.chunks.push(u8); }
  async close() {}
  blob(type = 'application/zip') { return new Blob(this.chunks, { type }); }
}

export class ZipWriter {
  /** @param sink object exposing async write(Uint8Array) and async close() */
  constructor(sink) {
    this.sink = sink;
    this.offset = 0;
    this.entries = [];
    this.closed = false;
  }

  get bytesWritten() { return this.offset; }

  async _put(u8) {
    await this.sink.write(u8);
    this.offset += u8.length;
  }

  /**
   * @param {string} name  path inside the archive, forward slashes
   * @param {Uint8Array} data
   */
  async add(name, data) {
    if (this.closed) throw new Error('ZipWriter already closed');
    if (this.entries.length >= 0xffff) throw new Error('ZIP entry limit reached (65535); split the bundle');

    const nameBytes = new TextEncoder().encode(name);
    const crc = crc32(data);
    let body = data;
    let method = 0;
    if (!STORE_EXT.test(name)) {
      const packed = await deflateRaw(data);
      if (packed.length < data.length) { body = packed; method = 8; }
    }

    const localOffset = this.offset;
    if (localOffset > 0xffffffff) throw new Error('ZIP would exceed 4GB (Zip64 unsupported); split the bundle');

    const { time, date } = dosDateTime(new Date());
    const head = new DataView(new ArrayBuffer(30));
    head.setUint32(0, 0x04034b50, true);
    head.setUint16(4, 20, true);      // version needed
    head.setUint16(6, 0x0800, true);  // UTF-8 names
    head.setUint16(8, method, true);
    head.setUint16(10, time, true);
    head.setUint16(12, date, true);
    head.setUint32(14, crc, true);
    head.setUint32(18, body.length, true);
    head.setUint32(22, data.length, true);
    head.setUint16(26, nameBytes.length, true);
    head.setUint16(28, 0, true);

    await this._put(new Uint8Array(head.buffer));
    await this._put(nameBytes);
    await this._put(body);

    this.entries.push({ nameBytes, crc, csize: body.length, usize: data.length, method, localOffset, time, date });
  }

  async addJson(name, obj) {
    await this.add(name, new TextEncoder().encode(JSON.stringify(obj, null, 2)));
  }

  async close() {
    if (this.closed) return;
    const cdStart = this.offset;
    for (const e of this.entries) {
      const cd = new DataView(new ArrayBuffer(46));
      cd.setUint32(0, 0x02014b50, true);
      cd.setUint16(4, 20, true);      // version made by
      cd.setUint16(6, 20, true);      // version needed
      cd.setUint16(8, 0x0800, true);
      cd.setUint16(10, e.method, true);
      cd.setUint16(12, e.time, true);
      cd.setUint16(14, e.date, true);
      cd.setUint32(16, e.crc, true);
      cd.setUint32(20, e.csize, true);
      cd.setUint32(24, e.usize, true);
      cd.setUint16(28, e.nameBytes.length, true);
      cd.setUint16(30, 0, true);      // extra
      cd.setUint16(32, 0, true);      // comment
      cd.setUint16(34, 0, true);      // disk
      cd.setUint16(36, 0, true);      // internal attrs
      cd.setUint32(38, 0, true);      // external attrs
      cd.setUint32(42, e.localOffset, true);
      await this._put(new Uint8Array(cd.buffer));
      await this._put(e.nameBytes);
    }
    const cdSize = this.offset - cdStart;

    const eocd = new DataView(new ArrayBuffer(22));
    eocd.setUint32(0, 0x06054b50, true);
    eocd.setUint16(4, 0, true);
    eocd.setUint16(6, 0, true);
    eocd.setUint16(8, this.entries.length, true);
    eocd.setUint16(10, this.entries.length, true);
    eocd.setUint32(12, cdSize, true);
    eocd.setUint32(16, cdStart, true);
    eocd.setUint16(20, 0, true);
    await this._put(new Uint8Array(eocd.buffer));

    this.closed = true;
    await this.sink.close();
  }
}

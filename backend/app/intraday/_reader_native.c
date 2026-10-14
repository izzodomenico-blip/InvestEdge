/* Optional offline prototype: same evidence checks over archive-owned rows.
 * No providers, clock or persistent value cache. SQL uses only the caller's
 * existing SQLite connection; unhandled codec cases use the Python oracle.
 * Keep the public Python reader/reducer as the reference implementation.
 */
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <math.h>
#include <string.h>
#ifdef _WIN32
#include <windows.h>
#include <wchar.h>
#endif

typedef struct sqlite3 sqlite3;
typedef struct sqlite3_stmt sqlite3_stmt;
typedef struct {
    int (*prepare)(sqlite3 *,const char *,int,sqlite3_stmt **,const char **);
    int (*step)(sqlite3_stmt *);
    int (*finalize)(sqlite3_stmt *);
    int (*readonly)(sqlite3_stmt *);
    int (*count)(sqlite3_stmt *);
    int (*parameter_count)(sqlite3_stmt *);
    int (*bind_null)(sqlite3_stmt *,int);
    int (*bind_int)(sqlite3_stmt *,int,long long);
    int (*bind_double)(sqlite3_stmt *,int,double);
    int (*bind_text)(sqlite3_stmt *,int,const char *,int,void (*)(void *));
    int (*bind_blob)(sqlite3_stmt *,int,const void *,int,void (*)(void *));
    int (*type)(sqlite3_stmt *,int);
    int (*bytes)(sqlite3_stmt *,int);
    long long (*integer)(sqlite3_stmt *,int);
    double (*real)(sqlite3_stmt *,int);
    const unsigned char *(*text)(sqlite3_stmt *,int);
    const void *(*blob)(sqlite3_stmt *,int);
} SqliteApi;

enum {
    PROFILE, FEED, MODE, PROVENANCE, GRADE, AVAILABLE, RECEIVED, PERSISTED,
    INGEST, PROVIDER, KIND, LISTING, EVENT, CAPTURE, ID, INTAKE, PAYLOAD,
    PAYLOAD_INTAKE, CAPTURE_ORDER, DEPENDENCY, PAYLOAD_JSON, PAYLOAD_HASH,
    DURABLE, OBSERVATION, FLOOR, ADMISSION, VERSION, FIELD_COUNT
};
static const char *names[FIELD_COUNT] = {
    "profile_id", "feed", "data_mode", "provenance", "replay_grade",
    "available_at_ns", "received_at_ns", "persisted_at_ns", "ingest_sequence",
    "provider", "kind", "listing_id", "event_time_ns", "capture_id", "id",
    "capture_ingest_sequence", "payload", "intake_sequence", "capture_order",
    "metadata_dependency", "payload_json", "payload_hash", "durable_at_ns",
    "observation_id", "availability_floor_ns", "admission_id", "version"
};
typedef struct {
    PyObject *keys[FIELD_COUNT]; PyObject *decoder, *decode_options, *sha256;
    PyObject *admission_version;
    PyObject *sqlite_module,*connection_type,*sqlite_error;
    SqliteApi sqlite;
    int sqlite_ready;
} State;

static PyObject *field(State *s, PyObject *row, int key) {
    PyObject *value = PyDict_GetItemWithError(row, s->keys[key]);
    if (value == NULL && !PyErr_Occurred()) PyErr_SetObject(PyExc_KeyError, s->keys[key]);
    return value;
}
static int invalid(const char *message) {
    PyErr_SetString(PyExc_ValueError, message);
    return -1;
}
static int timestamp(PyObject *value) {
    if (!PyLong_CheckExact(value)) return invalid("INVALID_TIMESTAMP");
    long long integer = PyLong_AsLongLong(value);
    if (PyErr_Occurred()) { PyErr_Clear(); return invalid("INVALID_TIMESTAMP"); }
    return integer < 0 ? invalid("INVALID_TIMESTAMP") : 0;
}
static PyObject *namespace_of(State *s, PyObject *row) {
    PyObject *result = PyTuple_New(5);
    if (!result) return NULL;
    for (int i=0; i<5; i++) {
        PyObject *value = field(s,row,i);
        if (!value) { Py_DECREF(result); return NULL; }
        PyTuple_SET_ITEM(result,i,Py_NewRef(value));
    }
    return result;
}
static PyObject *identity(State *s, PyObject *row, int anchor) {
    int fields[] = {PROVIDER,KIND,LISTING,EVENT,RECEIVED,CAPTURE};
    int count = anchor ? 6 : 4;
    PyObject *result = PyTuple_New(count);
    if (!result) return NULL;
    for (int i=0; i<count; i++) {
        PyObject *value = field(s,row,fields[i]);
        if (!value) { Py_DECREF(result); return NULL; }
        PyTuple_SET_ITEM(result,i,Py_NewRef(value));
    }
    return result;
}
static PyObject *local_order(State *s, PyObject *row, PyObject *anchor) {
    PyObject *received = field(s,row,RECEIVED), *ingest = field(s,row,INGEST);
    PyObject *id = field(s,row,ID), *payload = field(s,row,PAYLOAD);
    if (!received || !ingest || !id || !payload) return NULL;
    if (!PyDict_Check(payload)) { invalid("REPLAY_INPUT_INVALID"); return NULL; }
    PyObject *intake = PyDict_GetItemWithError(row,s->keys[INTAKE]);
    if (!intake) {
        if (PyErr_Occurred()) return NULL;
        intake = PyDict_GetItemWithError(payload,s->keys[PAYLOAD_INTAKE]);
        if (!intake && PyErr_Occurred()) return NULL;
        if (!intake) intake = ingest;
    }
    return PyTuple_Pack(5,received,anchor,intake,ingest,id);
}

static PyObject *select_market(PyObject *module, PyObject *args) {
    PyObject *input, *cutoff;
    int revisions;
    if (!PyArg_ParseTuple(args,"OOp:select_market",&input,&cutoff,&revisions)) return NULL;
    if (timestamp(cutoff)<0) return NULL;
    State *s = PyModule_GetState(module);
    PyObject *iterator = PyObject_GetIter(input), *rows = NULL, *expected = NULL;
    PyObject *anchors = NULL, *latest = NULL, *ordered = NULL, *result = NULL, *row;
    if (!iterator) return NULL;
    rows = PyList_New(0);
    anchors = PyDict_New();
    latest = PyDict_New();
    ordered = PyList_New(0);
    if (!rows || !anchors || !latest || !ordered) goto done;
    /* First materialize only visible owned rows, as visible_rows does. */
    while ((row = PyIter_Next(iterator))) {
        if (!PyDict_Check(row)) {
            Py_DECREF(row); invalid("REPLAY_INPUT_INVALID"); goto done;
        }
        PyObject *at = PyDict_GetItemWithError(row,s->keys[AVAILABLE]);
        int visible = at && at != Py_None ? PyObject_RichCompareBool(at,cutoff,Py_LE) : 0;
        if (PyErr_Occurred() || visible<0 || (visible && PyList_Append(rows,row)<0)) {
            Py_DECREF(row); goto done;
        }
        Py_DECREF(row);
    }
    if (PyErr_Occurred()) goto done;
    Py_ssize_t count = PyList_GET_SIZE(rows);
    if (count) {
        PyObject *primary = PyList_GET_ITEM(rows,0);
        for (Py_ssize_t i=0; i<count; i++) {
            row = PyList_GET_ITEM(rows,i);
            PyObject *dependency = PyDict_GetItemWithError(row,s->keys[DEPENDENCY]);
            int is_dependency = dependency ? PyObject_IsTrue(dependency) : 0;
            if (is_dependency<0 || PyErr_Occurred()) goto done;
            if (!is_dependency) { primary=row; break; }
        }
        expected = namespace_of(s,primary);
        if (!expected) goto done;
    }
    int ascending=1;
    PyObject *previous_event=NULL;
    for (Py_ssize_t i=0; i<count; i++) {
        row = PyList_GET_ITEM(rows,i);
        PyObject *at=field(s,row,AVAILABLE), *received=field(s,row,RECEIVED);
        PyObject *persisted=field(s,row,PERSISTED), *ingest=field(s,row,INGEST);
        if (!at || !received || !persisted || !ingest || timestamp(at)<0) goto done;
        PyObject *current=namespace_of(s,row);
        if (!current) goto done;
        int same=PyObject_RichCompareBool(current,expected,Py_EQ);
        Py_DECREF(current);
        if (same<0) goto done;
        if (!same) { invalid("MIXED_NAMESPACE"); goto done; }
        if (timestamp(received)<0 || timestamp(persisted)<0 || timestamp(ingest)<0) goto done;
        int early=PyObject_RichCompareBool(at,persisted,Py_LT);
        int backwards=PyObject_RichCompareBool(persisted,received,Py_LT);
        if (early<0 || backwards<0) goto done;
        if (early || backwards) { invalid("REPLAY_INPUT_INVALID"); goto done; }
        PyObject *event=field(s,row,EVENT), *provider=field(s,row,PROVIDER), *kind=field(s,row,KIND);
        PyObject *listing=field(s,row,LISTING), *capture=field(s,row,CAPTURE), *id=field(s,row,ID);
        PyObject *payload=field(s,row,PAYLOAD);
        if (!event || !provider || !kind || !listing || !capture || !id || !payload) goto done;
        if (!PyLong_CheckExact(event) || !PyLong_CheckExact(listing) || !PyLong_CheckExact(id)
            || !PyUnicode_CheckExact(provider) || !PyUnicode_CheckExact(kind) || !PyUnicode_CheckExact(capture)
            || !PyDict_CheckExact(payload)) ascending=0;
        if (ascending && previous_event) {
            int later=PyObject_RichCompareBool(event,previous_event,Py_GT);
            if (later<0) goto done;
            if (!later) ascending=0;
        }
        previous_event=event;
    }
    if (ascending) {
        /* Unique integer event times imply one row per logical identity and
         * anchor. All evidence/clocks/namespaces above were still validated.
         * Event time is the first output sort key, so order is already final.
         */
        for (Py_ssize_t i=0; i<count; i++) {
            row=PyList_GET_ITEM(rows,i);
            if (PyDict_SetItem(row,s->keys[CAPTURE_ORDER],field(s,row,ID))<0) goto done;
        }
        result=Py_NewRef(rows);
        goto done;
    }
    for (Py_ssize_t i=0; i<count; i++) {
        row=PyList_GET_ITEM(rows,i);
        PyObject *key=identity(s,row,1), *id=field(s,row,ID);
        if (!key || !id) { Py_XDECREF(key); goto done; }
        PyObject *previous=PyDict_GetItemWithError(anchors,key);
        int smaller=previous ? PyObject_RichCompareBool(id,previous,Py_LT) : 1;
        if (smaller<0 || PyErr_Occurred() || (smaller && PyDict_SetItem(anchors,key,id)<0)) {
            Py_DECREF(key); goto done;
        }
        Py_DECREF(key);
    }
    /* All anchors include losing revisions, regardless of cursor order. */
    for (Py_ssize_t i=0; i<count; i++) {
        row=PyList_GET_ITEM(rows,i);
        PyObject *key=identity(s,row,1);
        if (!key) goto done;
        PyObject *anchor=PyDict_GetItemWithError(anchors,key);
        Py_DECREF(key);
        if (!anchor || PyDict_SetItem(row,s->keys[CAPTURE_ORDER],anchor)<0) goto done;
        PyObject *rank=local_order(s,row,anchor);
        if (!rank) goto done;
        PyObject *entry=PyTuple_Pack(2,rank,row);
        Py_DECREF(rank);
        if (!entry) goto done;
        if (revisions) {
            if (PyList_Append(ordered,entry)<0) { Py_DECREF(entry); goto done; }
        } else {
            key=identity(s,row,0);
            if (!key) { Py_DECREF(entry); goto done; }
            PyObject *previous=PyDict_GetItemWithError(latest,key);
            int newer=previous ? PyObject_RichCompareBool(PyTuple_GET_ITEM(entry,0),PyTuple_GET_ITEM(previous,0),Py_GT) : 1;
            if (newer<0 || PyErr_Occurred() || (newer && PyDict_SetItem(latest,key,entry)<0)) {
                Py_DECREF(key); Py_DECREF(entry); goto done;
            }
            Py_DECREF(key);
        }
        Py_DECREF(entry);
    }
    if (!revisions) {
        Py_DECREF(ordered);
        ordered=PyDict_Values(latest);
        if (!ordered) goto done;
    }
    count=PyList_GET_SIZE(ordered);
    for (Py_ssize_t i=0; i<count; i++) {
        PyObject *entry=PyList_GET_ITEM(ordered,i), *rank=PyTuple_GET_ITEM(entry,0);
        row=PyTuple_GET_ITEM(entry,1);
        PyObject *event=field(s,row,EVENT), *at=field(s,row,AVAILABLE);
        if (!event || !at) goto done;
        PyObject *sortkey=PyTuple_Pack(7,event,at,PyTuple_GET_ITEM(rank,0),PyTuple_GET_ITEM(rank,1),
            PyTuple_GET_ITEM(rank,2),PyTuple_GET_ITEM(rank,3),PyTuple_GET_ITEM(rank,4));
        PyObject *ordinal=PyLong_FromSsize_t(i);
        PyObject *replacement=sortkey && ordinal ? PyTuple_Pack(3,sortkey,ordinal,row) : NULL;
        Py_XDECREF(sortkey); Py_XDECREF(ordinal);
        if (!replacement) goto done;
        /* SET_ITEM does not decrement an existing entry. */
        PyList_SET_ITEM(ordered,i,replacement);
        Py_DECREF(entry);
    }
    if (PyList_Sort(ordered)<0) goto done;
    result=PyList_New(count);
    if (!result) goto done;
    for (Py_ssize_t i=0; i<count; i++)
        PyList_SET_ITEM(result,i,Py_NewRef(PyTuple_GET_ITEM(PyList_GET_ITEM(ordered,i),2)));
done:
    Py_DECREF(iterator); Py_XDECREF(rows); Py_XDECREF(expected);
    Py_XDECREF(anchors); Py_XDECREF(latest); Py_XDECREF(ordered);
    return result;
}
/* Conservative certificate for the common canonical subset. Unusual keys,
 * long numeric tokens and deep trees always use the unchanged Python oracle.
 * UTF-8 comes from an existing Python Unicode object, never unchecked bytes.
 */
typedef struct { const char *text; Py_ssize_t size, at; } Json;
static int json_value(Json *j, unsigned depth, PyObject *decoded);
static int json_string(Json *j, int key, Py_ssize_t *start, Py_ssize_t *length) {
    if (j->at>=j->size || j->text[j->at++]!='"') return 0;
    *start=j->at;
    while (j->at<j->size) {
        unsigned char c=(unsigned char)j->text[j->at++];
        if (c=='"') { *length=j->at-*start-1; return 1; }
        if (c<32 || (key && (c=='\\' || c>=128))) return 0;
        if (c!='\\') continue;
        if (j->at>=j->size) return 0;
        c=(unsigned char)j->text[j->at++];
        if (c=='"' || c=='\\' || c=='b' || c=='f' || c=='n' || c=='r' || c=='t') continue;
        if (c!='u' || j->size-j->at<4 || j->text[j->at]!='0' || j->text[j->at+1]!='0') return 0;
        unsigned char a=(unsigned char)j->text[j->at+2], b=(unsigned char)j->text[j->at+3];
        if ((a!='0' && a!='1') || !((b>='0' && b<='9') || (b>='a' && b<='f'))) return 0;
        unsigned value=(a-'0')*16+(b<='9' ? b-'0' : b-'a'+10);
        if (value==8 || value==9 || value==10 || value==12 || value==13) return 0;
        j->at+=4;
    }
    return 0;
}
static int json_number(Json *j, PyObject *decoded) {
    Py_ssize_t start=j->at;
    int negative=j->text[j->at]=='-';
    if (negative && ++j->at==j->size) return 0;
    Py_ssize_t digits=j->at;
    if (j->text[j->at]=='0') ++j->at;
    else {
        if (j->text[j->at]<'1' || j->text[j->at]>'9') return 0;
        while (j->at<j->size && j->text[j->at]>='0' && j->text[j->at]<='9') ++j->at;
    }
    int floating=0;
    if (j->at<j->size && j->text[j->at]=='.') {
        floating=1;
        Py_ssize_t fraction=++j->at;
        while (j->at<j->size && j->text[j->at]>='0' && j->text[j->at]<='9') ++j->at;
        if (j->at==fraction) return 0;
    }
    if (j->at<j->size && (j->text[j->at]=='e' || j->text[j->at]=='E')) {
        floating=1;
        ++j->at;
        if (j->at<j->size && (j->text[j->at]=='+' || j->text[j->at]=='-')) ++j->at;
        Py_ssize_t exponent=j->at;
        while (j->at<j->size && j->text[j->at]>='0' && j->text[j->at]<='9') ++j->at;
        if (j->at==exponent) return 0;
    }
    Py_ssize_t length=j->at-start;
    if (!floating) return PyLong_CheckExact(decoded) && j->at-digits<=308
        && !(negative && length==2 && j->text[digits]=='0');
    if (!PyFloat_CheckExact(decoded) || length>=128) return 0;
    double value=PyFloat_AS_DOUBLE(decoded);
    if (!isfinite(value)) return 0;
    char *representation=PyOS_double_to_string(value,'r',0,Py_DTSF_ADD_DOT_0,NULL);
    if (!representation) return -1;
    int equal=strlen(representation)==(size_t)length && memcmp(representation,j->text+start,(size_t)length)==0;
    PyMem_Free(representation);
    return equal;
}
static int json_value(Json *j, unsigned depth, PyObject *decoded) {
    if (depth>128 || j->at>=j->size) return 0;
    char token=j->text[j->at];
    Py_ssize_t unused_start,unused_length;
    if (token=='"') return PyUnicode_CheckExact(decoded) && json_string(j,0,&unused_start,&unused_length);
    if (token=='{' || token=='[') {
        char end=token=='{' ? '}' : ']';
        if (token=='{' ? !PyDict_CheckExact(decoded) : !PyList_CheckExact(decoded)) return 0;
        ++j->at;
        if (j->at<j->size && j->text[j->at]==end) {
            ++j->at;
            return (token=='{' ? PyDict_Size(decoded) : PyList_GET_SIZE(decoded))==0;
        }
        Py_ssize_t previous_start=0,previous_length=0;
        Py_ssize_t position=0,index=0;
        int previous=0;
        for (;;) {
            PyObject *value;
            if (token=='{') {
                Py_ssize_t start,length;
                if (!json_string(j,1,&start,&length)) return 0;
                if (previous) {
                    Py_ssize_t common=length<previous_length ? length : previous_length;
                    int comparison=memcmp(j->text+previous_start,j->text+start,(size_t)common);
                    if (comparison>0 || (comparison==0 && previous_length>=length)) return 0;
                }
                previous=1; previous_start=start; previous_length=length;
                if (j->at>=j->size || j->text[j->at++]!=':') return 0;
                PyObject *key;
                if (!PyDict_Next(decoded,&position,&key,&value) || !PyUnicode_CheckExact(key)) return 0;
                Py_ssize_t key_size;
                const char *key_utf8=PyUnicode_AsUTF8AndSize(key,&key_size);
                if (!key_utf8) return -1;
                if (key_size!=length || memcmp(key_utf8,j->text+start,(size_t)length)!=0) return 0;
            } else {
                if (index>=PyList_GET_SIZE(decoded)) return 0;
                value=PyList_GET_ITEM(decoded,index);
            }
            ++index;
            int valid=json_value(j,depth+1,value);
            if (valid<=0) return valid;
            if (j->at>=j->size) return 0;
            char separator=j->text[j->at++];
            if (separator==end) return index==(token=='{' ? PyDict_Size(decoded) : PyList_GET_SIZE(decoded));
            if (separator!=',') return 0;
        }
    }
    const char *literal=token=='t' ? "true" : token=='f' ? "false" : token=='n' ? "null" : NULL;
    if (literal) {
        if (decoded!=(token=='t' ? Py_True : token=='f' ? Py_False : Py_None)) return 0;
        size_t size=strlen(literal);
        if ((size_t)(j->size-j->at)<size || memcmp(j->text+j->at,literal,size)!=0) return 0;
        j->at+=(Py_ssize_t)size;
        return 1;
    }
    return json_number(j,decoded);
}
static PyObject *decode_evidence_impl(PyObject *module, PyObject *raw, PyObject *fallback, int owned) {
    State *s=PyModule_GetState(module);
    if (!PyDict_CheckExact(raw)) return PyObject_CallOneArg(fallback,raw);
    PyObject *text=PyDict_GetItemWithError(raw,s->keys[PAYLOAD_JSON]);
    PyObject *hash=PyDict_GetItemWithError(raw,s->keys[PAYLOAD_HASH]);
    if (PyErr_Occurred()) return NULL;
    if (!text || !hash || !PyUnicode_CheckExact(text) || !PyUnicode_CheckExact(hash))
        return PyObject_CallOneArg(fallback,raw);
    Py_ssize_t size;
    const char *utf8=PyUnicode_AsUTF8AndSize(text,&size);
    if (!utf8) { PyErr_Clear(); return PyObject_CallOneArg(fallback,raw); }
    if (size<2 || size>1048576 || utf8[0]!='{' || utf8[size-1]!='}')
        return PyObject_CallOneArg(fallback,raw);
    PyObject *decode_args=PyTuple_Pack(1,text);
    if (!decode_args) return NULL;
    PyObject *payload=PyObject_Call(s->decoder,decode_args,s->decode_options);
    Py_DECREF(decode_args);
    if (!payload) {
        if (!PyErr_ExceptionMatches(PyExc_ValueError)) return NULL;
        PyErr_Clear(); return PyObject_CallOneArg(fallback,raw);
    }
    Json json={utf8,size,0};
    int canonical=json_value(&json,0,payload);
    if (canonical<0) { Py_DECREF(payload); return NULL; }
    if (!canonical || json.at!=size) { Py_DECREF(payload); return PyObject_CallOneArg(fallback,raw); }
    PyObject *bytes=PyBytes_FromStringAndSize(utf8,size);
    PyObject *digest=bytes ? PyObject_CallOneArg(s->sha256,bytes) : NULL;
    Py_XDECREF(bytes);
    if (!digest) { Py_DECREF(payload); return NULL; }
    PyObject *hex=PyObject_CallMethod(digest,"hexdigest",NULL);
    Py_DECREF(digest);
    if (!hex) { Py_DECREF(payload); return NULL; }
    int equal=PyObject_RichCompareBool(hex,hash,Py_EQ);
    Py_DECREF(hex);
    if (equal<0) { Py_DECREF(payload); return NULL; }
    if (!equal) { Py_DECREF(payload); return PyObject_CallOneArg(fallback,raw); }
    PyObject *result=owned ? Py_NewRef(raw) : PyDict_Copy(raw);
    if (result && PyDict_SetItem(result,s->keys[PAYLOAD],payload)<0) Py_CLEAR(result);
    Py_DECREF(payload);
    return result;
}
static PyObject *decode_evidence(PyObject *module, PyObject *args) {
    PyObject *raw,*fallback;
    if (!PyArg_ParseTuple(args,"OO:decode_evidence",&raw,&fallback)) return NULL;
    return decode_evidence_impl(module,raw,fallback,0);
}
static PyObject *decode_owned(PyObject *module, PyObject *raw, PyObject *fallback) {
    return decode_evidence_impl(module,raw,fallback,1);
}
static int literal(const char **at, const char *end, const char *value) {
    size_t size=strlen(value);
    if ((size_t)(end-*at)<size || memcmp(*at,value,size)!=0) return 0;
    *at+=size;
    return 1;
}
static int decimal(const char **at, const char *end, long long *result) {
    const char *start=*at;
    if (start==end || *start<'0' || *start>'9') return 0;
    long long value=0;
    while (*at<end && **at>='0' && **at<='9') {
        int digit=*(*at)++-'0';
        if (value>(LLONG_MAX-digit)/10) return 0;
        value=value*10+digit;
    }
    if (*at-start>1 && *start=='0') return 0;
    *result=value;
    return 1;
}
static PyObject *receipt_fields(PyObject *module, PyObject *raw, PyObject *text, PyObject *hash, PyObject *fallback) {
    State *s=PyModule_GetState(module);
    if (PyUnicode_CheckExact(text) && PyUnicode_CheckExact(hash)) {
        Py_ssize_t size;
        const char *utf8=PyUnicode_AsUTF8AndSize(text,&size);
        if (!utf8) { PyErr_Clear(); goto fallback; }
        if (size<2 || size>1048576) goto fallback;
        const char *at=utf8, *end=utf8+size;
        long long durable,observation;
        if (!literal(&at,end,"{\"durable_at_ns\":") || !decimal(&at,end,&durable)
            || !literal(&at,end,",\"observation_id\":") || !decimal(&at,end,&observation)
            || !literal(&at,end,",\"payload_hash\":\"") || end-at<64) goto fallback;
        const char *admitted_hash=at;
        for (int i=0; i<64; i++,at++) if (!(*at>='0' && *at<='9') && !(*at>='a' && *at<='f')) goto fallback;
        if (!literal(&at,end,"\",\"version\":\"intraday-admission-v1\"}") || at!=end) goto fallback;
        /* The exact four-field v1 spelling above certifies canonicality and
         * finite int64 types. SHA is still recomputed for every receipt.
         */
        PyObject *bytes=PyBytes_FromStringAndSize(utf8,size);
        PyObject *digest=bytes ? PyObject_CallOneArg(s->sha256,bytes) : NULL;
        Py_XDECREF(bytes);
        if (!digest) return NULL;
        PyObject *hex=PyObject_CallMethod(digest,"hexdigest",NULL);
        Py_DECREF(digest);
        if (!hex) return NULL;
        int equal=PyObject_RichCompareBool(hex,hash,Py_EQ);
        Py_DECREF(hex);
        if (equal<0) return NULL;
        if (!equal) goto fallback;
        PyObject *a=PyLong_FromLongLong(durable), *b=PyLong_FromLongLong(observation);
        PyObject *c=PyUnicode_FromStringAndSize(admitted_hash,64);
        PyObject *result=a && b && c ? PyTuple_Pack(4,a,b,c,s->admission_version) : NULL;
        Py_XDECREF(a); Py_XDECREF(b); Py_XDECREF(c);
        return result;
    }
fallback:
    if (!raw) {
        raw=PyDict_New();
        if (!raw) return NULL;
        if (PyDict_SetItem(raw,s->keys[PAYLOAD_JSON],text)<0 || PyDict_SetItem(raw,s->keys[PAYLOAD_HASH],hash)<0) {
            Py_DECREF(raw); return NULL;
        }
    } else Py_INCREF(raw);
    PyObject *row=decode_evidence_impl(module,raw,fallback,0);
    Py_DECREF(raw);
    if (!row) return NULL;
    PyObject *payload=field(s,row,PAYLOAD);
    if (!payload) { Py_DECREF(row); return NULL; }
    int keys[]={DURABLE,OBSERVATION,PAYLOAD_HASH,VERSION};
    PyObject *result=PyTuple_New(4);
    if (result) for (int i=0; i<4; i++) {
        PyObject *value=PyDict_GetItemWithError(payload,s->keys[keys[i]]);
        if (!value && PyErr_Occurred()) { Py_CLEAR(result); break; }
        PyTuple_SET_ITEM(result,i,Py_NewRef(value ? value : Py_None));
    }
    Py_DECREF(row);
    return result;
}
static PyObject *receipt_values(PyObject *module, PyObject *args) {
    PyObject *raw,*fallback;
    if (!PyArg_ParseTuple(args,"OO:receipt_values",&raw,&fallback)) return NULL;
    State *s=PyModule_GetState(module);
    PyObject *text=NULL,*hash=NULL;
    if (PyDict_CheckExact(raw)) {
        text=PyDict_GetItemWithError(raw,s->keys[PAYLOAD_JSON]);
        hash=PyDict_GetItemWithError(raw,s->keys[PAYLOAD_HASH]);
        if (PyErr_Occurred()) return NULL;
    }
    return receipt_fields(module,raw,text ? text : Py_None,hash ? hash : Py_None,fallback);
}
static PyObject *read_market(PyObject *module, PyObject *args) {
    PyObject *input,*source,*positions,*cutoff,*start,*end,*listings,*fallback,*check_ns,*store_error;
    int revisions;
    if (!PyArg_ParseTuple(args,"OOOOOOOpOOO:read_market",&input,&source,&positions,&cutoff,&start,&end,
        &listings,&revisions,&fallback,&check_ns,&store_error)) return NULL;
    if (!PyTuple_CheckExact(source) || !PyTuple_CheckExact(positions) || PyTuple_GET_SIZE(positions)!=4) {
        PyErr_SetString(PyExc_TypeError,"NATIVE_CURSOR_SHAPE"); return NULL;
    }
    Py_ssize_t n=PyTuple_GET_SIZE(source), proof_index[4];
    for (Py_ssize_t i=0; i<n; i++) {
        if (!PyUnicode_CheckExact(PyTuple_GET_ITEM(source,i))) {
            PyErr_SetString(PyExc_TypeError,"NATIVE_CURSOR_SHAPE"); return NULL;
        }
    }
    for (int i=0; i<4; i++) {
        PyObject *index=PyTuple_GET_ITEM(positions,i);
        if (!PyLong_CheckExact(index)) { PyErr_SetString(PyExc_TypeError,"NATIVE_CURSOR_SHAPE"); return NULL; }
        proof_index[i]=PyLong_AsSsize_t(index);
        if (PyErr_Occurred()) return NULL;
        if (proof_index[i]<n || proof_index[i]>=n+4) { PyErr_SetString(PyExc_TypeError,"NATIVE_CURSOR_SHAPE"); return NULL; }
    }
    State *s=PyModule_GetState(module);
    PyObject *iterator=PyObject_GetIter(input), *rows=PyList_New(0), *values=NULL;
    PyObject *raw=NULL,*proof_row=NULL,*item=NULL,*result=NULL;
    if (!iterator || !rows) goto done;
    while ((values=PyIter_Next(iterator))) {
        if (!PyTuple_CheckExact(values) || PyTuple_GET_SIZE(values)!=n+4) {
            PyErr_SetString(PyExc_TypeError,"NATIVE_CURSOR_SHAPE"); goto done;
        }
        raw=PyDict_New();
        if (!raw) goto done;
        for (Py_ssize_t i=0; i<n; i++)
            if (PyDict_SetItem(raw,PyTuple_GET_ITEM(source,i),PyTuple_GET_ITEM(values,i))<0) goto done;
        proof_row=receipt_fields(module,NULL,PyTuple_GET_ITEM(values,proof_index[0]),PyTuple_GET_ITEM(values,proof_index[1]),fallback);
        if (!proof_row) goto done;
        item=decode_owned(module,raw,fallback);
        if (!item) goto done;
        PyObject *durable=PyTuple_GET_ITEM(proof_row,0);
        PyObject *checked=PyObject_CallOneArg(check_ns,durable);
        if (!checked) goto done;
        Py_DECREF(checked);
        PyObject *id=field(s,item,ID), *hash=field(s,item,PAYLOAD_HASH), *persisted=field(s,item,PERSISTED);
        PyObject *proof_id=PyTuple_GET_ITEM(proof_row,1);
        PyObject *proof_hash=PyTuple_GET_ITEM(proof_row,2);
        if (!id || !hash || !persisted || PyErr_Occurred()) goto done;
        int same_id=PyObject_RichCompareBool(proof_id ? proof_id : Py_None,id,Py_EQ);
        int same_hash=PyObject_RichCompareBool(proof_hash ? proof_hash : Py_None,hash,Py_EQ);
        int early=PyObject_RichCompareBool(durable,persisted,Py_LT);
        if (same_id<0 || same_hash<0 || early<0) goto done;
        if (!same_id || !same_hash || early) { PyErr_SetString(store_error,"OBSERVATION_INVALID"); goto done; }
        PyObject *at=PyTuple_GET_ITEM(values,proof_index[2]), *floor=field(s,item,FLOOR);
        if (!floor) goto done;
        int later=PyObject_RichCompareBool(durable,at,Py_GT);
        if (later<0) goto done;
        if (later) at=durable;
        later=PyObject_RichCompareBool(floor,at,Py_GT);
        if (later<0) goto done;
        if (later) at=floor;
        if (PyDict_SetItem(item,s->keys[AVAILABLE],at)<0) goto done;
        int keep=PyObject_RichCompareBool(at,cutoff,Py_LE);
        if (keep<0) goto done;
        if (keep && listings!=Py_None) {
            PyObject *listing=field(s,item,LISTING);
            if (!listing) goto done;
            keep=PySequence_Contains(listings,listing);
            if (keep<0) goto done;
        }
        if (keep && start!=Py_None) {
            PyObject *event=field(s,item,EVENT);
            if (!event) goto done;
            int excluded=PyObject_RichCompareBool(event,start,Py_LT);
            if (excluded<0) goto done;
            keep=!excluded;
        }
        if (keep && end!=Py_None) {
            PyObject *event=field(s,item,EVENT);
            if (!event) goto done;
            int excluded=PyObject_RichCompareBool(event,end,Py_GE);
            if (excluded<0) goto done;
            keep=!excluded;
        }
        if (keep) {
            PyObject *payload=field(s,item,PAYLOAD), *ingest=field(s,item,INGEST);
            if (!payload || !ingest) goto done;
            PyObject *intake=PyDict_GetItemWithError(payload,s->keys[PAYLOAD_INTAKE]);
            if (PyErr_Occurred()) goto done;
            if (!intake) intake=ingest;
            if (PyDict_SetItem(item,s->keys[ADMISSION],PyTuple_GET_ITEM(values,proof_index[3]))<0
                || PyDict_SetItem(item,s->keys[INTAKE],intake)<0 || PyList_Append(rows,item)<0) goto done;
        }
        Py_CLEAR(values); Py_CLEAR(raw); Py_CLEAR(proof_row); Py_CLEAR(item);
    }
    if (PyErr_Occurred()) goto done;
    PyObject *select_args=PyTuple_Pack(3,rows,cutoff,revisions ? Py_True : Py_False);
    if (select_args) { result=select_market(module,select_args); Py_DECREF(select_args); }
done:
    Py_XDECREF(iterator); Py_XDECREF(rows); Py_XDECREF(values); Py_XDECREF(raw);
    Py_XDECREF(proof_row); Py_XDECREF(item);
    return result;
}
/* ABI experiment, never an automatic replacement for DB-API. The only private
 * layout facts used are the db/state pointer prefix and detect_types. Verified
 * against CPython v3.14.7 Modules/_sqlite/connection.h; require that exact
 * runtime/build, exact type/basicsize, default text conversion and owner thread.
 * Unsupported contexts must stay on the Python path.
 */
static int sqlite_api(State *s) {
    if (s->sqlite_ready) return 1;
#if defined(_WIN32) && !defined(Py_GIL_DISABLED) && PY_VERSION_HEX == 0x030e07f0
    if (sizeof(void *)!=8 || Py_Version!=0x030e07f0UL) return 0;
    PyObject *implementation=PySys_GetObject("implementation");
    PyObject *name=implementation ? PyObject_GetAttrString(implementation,"name") : NULL;
    if (!name) return -1;
    int cpython=PyUnicode_CompareWithASCIIString(name,"cpython")==0;
    Py_DECREF(name);
    if (!cpython) return 0;
    if (!s->sqlite_module) {
        s->sqlite_module=PyImport_ImportModule("_sqlite3");
        if (!s->sqlite_module) return -1;
        s->connection_type=PyObject_GetAttrString(s->sqlite_module,"Connection");
        s->sqlite_error=PyObject_GetAttrString(s->sqlite_module,"OperationalError");
        if (!s->connection_type || !s->sqlite_error) return -1;
    }
    PyObject *filename=PyObject_GetAttrString(s->sqlite_module,"__file__");
    if (!filename) return -1;
    wchar_t *path=PyUnicode_AsWideCharString(filename,NULL);
    Py_DECREF(filename);
    if (!path) return -1;
    wchar_t *slash=wcsrchr(path,L'\\'), *forward=wcsrchr(path,L'/');
    if (!slash || (forward && forward>slash)) slash=forward;
    if (!slash || wcslen(slash+1)<wcslen(L"sqlite3.dll")) { PyMem_Free(path); return 0; }
    wcscpy(slash+1,L"sqlite3.dll");
    HMODULE library=GetModuleHandleW(path);
    PyMem_Free(path);
    if (!library) return 0;
#define LOAD(member,name) do { FARPROC symbol=GetProcAddress(library,name); \
    if (!symbol || sizeof(symbol)!=sizeof(s->sqlite.member)) return 0; \
    memcpy(&s->sqlite.member,&symbol,sizeof(symbol)); } while(0)
    LOAD(prepare,"sqlite3_prepare_v2"); LOAD(step,"sqlite3_step"); LOAD(finalize,"sqlite3_finalize");
    LOAD(readonly,"sqlite3_stmt_readonly"); LOAD(count,"sqlite3_column_count");
    LOAD(parameter_count,"sqlite3_bind_parameter_count"); LOAD(bind_null,"sqlite3_bind_null");
    LOAD(bind_int,"sqlite3_bind_int64"); LOAD(bind_double,"sqlite3_bind_double");
    LOAD(bind_text,"sqlite3_bind_text"); LOAD(bind_blob,"sqlite3_bind_blob");
    LOAD(type,"sqlite3_column_type"); LOAD(bytes,"sqlite3_column_bytes");
    LOAD(integer,"sqlite3_column_int64"); LOAD(real,"sqlite3_column_double");
    LOAD(text,"sqlite3_column_text"); LOAD(blob,"sqlite3_column_blob");
#undef LOAD
    s->sqlite_ready=1;
    return 1;
#else
    return 0;
#endif
}
typedef struct { SqliteApi api; sqlite3_stmt *stmt; int pending,done; } Query;
static void query_finish(Query *q) {
    if (q->stmt) q->api.finalize(q->stmt);
    q->stmt=NULL;
    q->done=1;
}
static void query_free(PyObject *capsule) {
    if (!PyCapsule_IsValid(capsule,"investedge.readonly_stmt")) return;
    Query *q=PyCapsule_GetPointer(capsule,"investedge.readonly_stmt");
    query_finish(q);
    PyMem_Free(q);
}
static PyObject *query_next(PyObject *self, PyObject *Py_UNUSED(ignored)) {
    Query *q=PyCapsule_GetPointer(PyTuple_GET_ITEM(self,0),"investedge.readonly_stmt");
    if (!q) return NULL;
    if (q->done) Py_RETURN_NONE;
    /* The public bound getlimit method checks closed/owner-thread state. */
    PyObject *checked=PyObject_CallOneArg(PyTuple_GET_ITEM(self,1),PyTuple_GET_ITEM(self,4));
    if (!checked) { query_finish(q); return NULL; }
    Py_DECREF(checked);
    PyObject *factory=PyObject_GetAttrString(PyTuple_GET_ITEM(self,3),"text_factory");
    if (!factory) { query_finish(q); return NULL; }
    int plain=factory==(PyObject *)&PyUnicode_Type;
    Py_DECREF(factory);
    if (!plain) { query_finish(q); PyErr_SetString(PyExc_NotImplementedError,"NATIVE_ABI_UNSUPPORTED"); return NULL; }
    int status=q->pending ? 100 : q->api.step(q->stmt);
    q->pending=0;
    if (status==101) { query_finish(q); Py_RETURN_NONE; }
    if (status!=100) { query_finish(q); PyErr_SetString(PyTuple_GET_ITEM(self,2),"NATIVE_READ_FAILED"); return NULL; }
    int count=q->api.count(q->stmt);
    PyObject *row=PyTuple_New(count);
    if (!row) { query_finish(q); return NULL; }
    for (int i=0; i<count; i++) {
        int type=q->api.type(q->stmt,i);
        PyObject *value=NULL;
        if (type==1) value=PyLong_FromLongLong(q->api.integer(q->stmt,i));
        else if (type==2) value=PyFloat_FromDouble(q->api.real(q->stmt,i));
        else if (type==5) value=Py_NewRef(Py_None);
        else {
            const void *data=type==3 ? (const void *)q->api.text(q->stmt,i) : q->api.blob(q->stmt,i);
            int size=q->api.bytes(q->stmt,i);
            if (size && !data) PyErr_NoMemory();
            else if (type==3) value=PyUnicode_DecodeUTF8(data ? data : "",size,"strict");
            else value=PyBytes_FromStringAndSize(data ? data : "",size);
        }
        if (!value) {
            Py_DECREF(row);
            query_finish(q);
            if (!PyErr_ExceptionMatches(PyExc_MemoryError)) {
                PyErr_Clear(); PyErr_SetString(PyTuple_GET_ITEM(self,2),"NATIVE_READ_FAILED");
            }
            return NULL;
        }
        PyTuple_SET_ITEM(row,i,value);
    }
    return row;
}
static PyMethodDef next_method={"_next_readonly_row",query_next,METH_NOARGS,NULL};
static PyObject *query(PyObject *module, PyObject *args) {
    PyObject *connection,*sql,*bindings;
    if (!PyArg_ParseTuple(args,"OOO:query",&connection,&sql,&bindings)) return NULL;
    State *s=PyModule_GetState(module);
    int supported=sqlite_api(s);
    if (supported<0) return NULL;
    if (!supported || (PyObject *)Py_TYPE(connection)!=s->connection_type || Py_TYPE(connection)->tp_basicsize!=216)
        goto unsupported;
    PyObject *getlimit=PyObject_GetAttrString(connection,"getlimit");
    PyObject *category=PyLong_FromLong(2);
    PyObject *checked=getlimit && category ? PyObject_CallOneArg(getlimit,category) : NULL;
    if (!checked) { Py_XDECREF(getlimit); Py_XDECREF(category); return NULL; }
    Py_DECREF(checked);
    int detect_types;
    sqlite3 *db;
    memcpy(&db,(const char *)connection+sizeof(PyObject),sizeof(db));
    memcpy(&detect_types,(const char *)connection+sizeof(PyObject)+2*sizeof(void *),sizeof(detect_types));
    PyObject *factory=PyObject_GetAttrString(connection,"text_factory");
    if (!factory) { Py_DECREF(getlimit); Py_DECREF(category); return NULL; }
    int plain=factory==(PyObject *)&PyUnicode_Type;
    Py_DECREF(factory);
    if (!plain || detect_types || !PyUnicode_CheckExact(sql) || !PyTuple_CheckExact(bindings)) {
        Py_DECREF(getlimit); Py_DECREF(category); goto unsupported;
    }
    Py_ssize_t size;
    const char *text=PyUnicode_AsUTF8AndSize(sql,&size);
    if (!text) { Py_DECREF(getlimit); Py_DECREF(category); return NULL; }
    if (size>1048576 || (Py_ssize_t)strlen(text)!=size) {
        Py_DECREF(getlimit); Py_DECREF(category); invalid("NATIVE_READ_ONLY"); return NULL;
    }
    /* PRAGMA can mutate connection state during prepare itself. Only the
     * controlled SELECT/WITH domain may reach prepare; readonly/tail checks
     * below still reject mutating CTEs and multiple statements before step. */
    const char *first=text;
    while (*first==' ' || *first=='\t' || *first=='\r' || *first=='\n') ++first;
    char token[7]={0};
    int length=0;
    while (length<6 && ((first[length]>='a' && first[length]<='z') || (first[length]>='A' && first[length]<='Z'))) {
        char letter=first[length];
        token[length++]=(letter>='a' && letter<='z') ? (char)(letter-'a'+'A') : letter;
    }
    char boundary=first[length];
    if ((strcmp(token,"SELECT") && strcmp(token,"WITH")) ||
        (boundary!=' ' && boundary!='\t' && boundary!='\r' && boundary!='\n' && boundary!='(')) {
        Py_DECREF(getlimit); Py_DECREF(category); invalid("NATIVE_READ_ONLY"); return NULL;
    }
    PyObject *adapters=PyObject_GetAttrString(s->sqlite_module,"adapters");
    PyObject *protocol=PyObject_GetAttrString(s->sqlite_module,"PrepareProtocol");
    if (!adapters || !protocol) {
        Py_XDECREF(adapters); Py_XDECREF(protocol); Py_DECREF(getlimit); Py_DECREF(category); return NULL;
    }
    int adapted=0;
    for (Py_ssize_t i=0; i<PyTuple_GET_SIZE(bindings) && !adapted; i++) {
        PyObject *key=PyTuple_Pack(2,(PyObject *)Py_TYPE(PyTuple_GET_ITEM(bindings,i)),protocol);
        if (!key) { adapted=-1; break; }
        adapted=PySequence_Contains(adapters,key);
        Py_DECREF(key);
    }
    Py_DECREF(adapters); Py_DECREF(protocol);
    if (adapted) {
        Py_DECREF(getlimit); Py_DECREF(category);
        if (adapted<0) return NULL;
        goto unsupported;
    }
    Query *q=PyMem_Calloc(1,sizeof(Query));
    if (!q) { Py_DECREF(getlimit); Py_DECREF(category); return PyErr_NoMemory(); }
    q->api=s->sqlite;
    PyObject *capsule=PyCapsule_New(q,"investedge.readonly_stmt",query_free);
    if (!capsule) { PyMem_Free(q); Py_DECREF(getlimit); Py_DECREF(category); return NULL; }
    const char *tail;
    int status=q->api.prepare(db,text,(int)size,&q->stmt,&tail);
    if (status!=0) { PyErr_SetString(s->sqlite_error,"NATIVE_READ_FAILED"); goto failed; }
    while (*tail==' ' || *tail=='\t' || *tail=='\r' || *tail=='\n') ++tail;
    if (!q->stmt || *tail || !q->api.readonly(q->stmt) || q->api.count(q->stmt)==0) {
        invalid("NATIVE_READ_ONLY"); goto failed;
    }
    if (q->api.parameter_count(q->stmt)!=PyTuple_GET_SIZE(bindings)) {
        PyErr_SetString(PyExc_NotImplementedError,"NATIVE_ABI_UNSUPPORTED"); goto failed;
    }
    for (Py_ssize_t i=0; i<PyTuple_GET_SIZE(bindings); i++) {
        PyObject *value=PyTuple_GET_ITEM(bindings,i);
        int parameter=(int)i+1;
        if (value==Py_None) status=q->api.bind_null(q->stmt,parameter);
        else if (PyLong_CheckExact(value)) {
            long long integer=PyLong_AsLongLong(value);
            if (PyErr_Occurred()) goto failed;
            status=q->api.bind_int(q->stmt,parameter,integer);
        } else if (PyFloat_CheckExact(value)) status=q->api.bind_double(q->stmt,parameter,PyFloat_AS_DOUBLE(value));
        else if (PyUnicode_CheckExact(value)) {
            const char *data=PyUnicode_AsUTF8AndSize(value,&size);
            if (!data) goto failed;
            if (size>INT_MAX) { PyErr_SetString(PyExc_NotImplementedError,"NATIVE_ABI_UNSUPPORTED"); goto failed; }
            status=q->api.bind_text(q->stmt,parameter,data,(int)size,(void (*)(void *))-1);
        } else if (PyBytes_CheckExact(value)) {
            size=PyBytes_GET_SIZE(value);
            if (size>INT_MAX) { PyErr_SetString(PyExc_NotImplementedError,"NATIVE_ABI_UNSUPPORTED"); goto failed; }
            status=q->api.bind_blob(q->stmt,parameter,PyBytes_AS_STRING(value),(int)size,(void (*)(void *))-1);
        } else { PyErr_SetString(PyExc_NotImplementedError,"NATIVE_ABI_UNSUPPORTED"); goto failed; }
        if (status!=0) { PyErr_SetString(s->sqlite_error,"NATIVE_READ_FAILED"); goto failed; }
    }
    status=q->api.step(q->stmt);
    if (status==100) q->pending=1;
    else if (status==101) q->done=1;
    else { PyErr_SetString(s->sqlite_error,"NATIVE_READ_FAILED"); goto failed; }
    PyObject *self=PyTuple_Pack(5,capsule,getlimit,s->sqlite_error,connection,category);
    Py_DECREF(capsule); Py_DECREF(getlimit); Py_DECREF(category);
    if (!self) return NULL;
    PyObject *callable=PyCFunction_NewEx(&next_method,self,NULL);
    Py_DECREF(self);
    if (!callable) return NULL;
    PyObject *result=PyCallIter_New(callable,Py_None);
    Py_DECREF(callable);
    return result;
failed:
    Py_DECREF(capsule); Py_DECREF(getlimit); Py_DECREF(category);
    return NULL;
unsupported:
    PyErr_SetString(PyExc_NotImplementedError,"NATIVE_ABI_UNSUPPORTED");
    return NULL;
}
static int traverse(PyObject *module, visitproc visit, void *arg) {
    State *s=PyModule_GetState(module);
    for (int i=0; i<FIELD_COUNT; i++) Py_VISIT(s->keys[i]);
    Py_VISIT(s->decoder); Py_VISIT(s->decode_options); Py_VISIT(s->sha256);
    Py_VISIT(s->admission_version);
    Py_VISIT(s->sqlite_module); Py_VISIT(s->connection_type); Py_VISIT(s->sqlite_error);
    return 0;
}
static int clear(PyObject *module) {
    State *s=PyModule_GetState(module);
    for (int i=0; i<FIELD_COUNT; i++) Py_CLEAR(s->keys[i]);
    Py_CLEAR(s->decoder); Py_CLEAR(s->decode_options); Py_CLEAR(s->sha256);
    Py_CLEAR(s->admission_version);
    Py_CLEAR(s->sqlite_module); Py_CLEAR(s->connection_type); Py_CLEAR(s->sqlite_error);
    return 0;
}
static PyMethodDef methods[] = {
    {"select_market",select_market,METH_VARARGS,"Select fresh decoded market rows; no evidence checks are skipped."},
    {"decode_evidence",decode_evidence,METH_VARARGS,"Canonical subset certificate and SHA; all other inputs use the Python oracle."},
    {"receipt_values",receipt_values,METH_VARARGS,"Validate full receipt evidence and return its typed binding fields."},
    {"read_market",read_market,METH_VARARGS,"Decode every RAW and receipt before selecting market versions."},
    {"query",query,METH_VARARGS,"Experimental readonly cursor on the same CPython 3.14.7 Windows connection."},
    {NULL,NULL,0,NULL}
};
static struct PyModuleDef definition = {
    PyModuleDef_HEAD_INIT,"_investedge_reader_native",NULL,sizeof(State),methods,NULL,traverse,clear,NULL
};
PyMODINIT_FUNC PyInit__investedge_reader_native(void) {
    PyObject *module=PyModule_Create(&definition);
    if (!module) return NULL;
    State *s=PyModule_GetState(module);
    for (int i=0; i<FIELD_COUNT; i++) {
        s->keys[i]=PyUnicode_InternFromString(names[i]);
        if (!s->keys[i]) { Py_DECREF(module); return NULL; }
    }
    PyObject *core=PyImport_ImportModule("pydantic_core"), *hashlib=PyImport_ImportModule("hashlib");
    if (core) { s->decoder=PyObject_GetAttrString(core,"from_json"); Py_DECREF(core); }
    if (hashlib) { s->sha256=PyObject_GetAttrString(hashlib,"sha256"); Py_DECREF(hashlib); }
    s->decode_options=Py_BuildValue("{s:O,s:O}","allow_inf_nan",Py_False,"cache_strings",Py_False);
    s->admission_version=PyUnicode_InternFromString("intraday-admission-v1");
    if (!s->decoder || !s->sha256 || !s->decode_options || !s->admission_version) { Py_DECREF(module); return NULL; }
    return module;
}

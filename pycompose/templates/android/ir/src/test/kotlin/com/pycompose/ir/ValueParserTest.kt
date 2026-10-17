package com.pycompose.ir

import com.pycompose.ir.generated.Button
import com.pycompose.ir.generated.ValueContract
import com.pycompose.ir.generated.WireTextStyle
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class ValueParserTest {
    @Test fun componentPropsPreserveNullVersusAbsentWhenDecodedAndEncoded() {
        fun parse(extra: String): com.pycompose.ir.generated.IRRoot =
            IrParser()
                .parse(
                    """{"version":"0.1.0","schemaVersion":"1.11.0","root":{
              "id":"root","type":"Button","props":{"text":"Save","onClick":"increment"$extra}}}""",
                ).getOrThrow()
                .snapshot
        val omitted = parse("")
        val explicitNull = parse(",\"elevation\":null")
        assertEquals(OptionalValue.Absent, (omitted.root as Button).props.elevation)
        assertEquals(OptionalValue.Null, (explicitNull.root as Button).props.elevation)
        assertFalse(Json.encodeToString(omitted).contains("elevation"))
        assertTrue(Json.encodeToString(explicitNull).contains("\"elevation\":null"))
    }

    @Test fun floatLimitsAreCheckedBeforeNarrowingIntegerPrecision() {
        assertTrue(
            ValueParser
                .validate(
                    Json.parseToJsonElement(
                        """{"type":"Dp","value":340282346638528859811704183484516925441}""",
                    ),
                    "Dp",
                ).isFailure,
        )
        assertTrue(
            ValueParser
                .validate(
                    Json.parseToJsonElement(
                        """{"type":"Dp","value":3.4028234663852886e38}""",
                    ),
                    "Dp",
                ).isSuccess,
        )
    }

    @Test fun absentNullAndProvidedFieldsRemainDistinct() {
        val omitted =
            ValueContract.readTextStyle(
                Json.parseToJsonElement("""{"type":"TextStyle"}"""),
            ) as WireTextStyle
        val explicitNull =
            ValueContract.readTextStyle(
                Json.parseToJsonElement("""{"type":"TextStyle","fontFamily":null}"""),
            ) as WireTextStyle
        assertFalse("fontFamily" in omitted.supplied)
        assertTrue("fontFamily" in explicitNull.supplied)
        assertNull(explicitNull.fontFamily)
    }

    @Test fun malformedValuesFailBeforeNativeConstruction() {
        val invalid =
            listOf(
                """{"type":"Dp","value":true}""" to "Dp",
                """{"type":"Dp","value":"8"}""" to "Dp",
                """{"type":"Dp","value":1e39}""" to "Dp",
                """{"type":"Dp","value":1e-50}""" to "Dp",
                """{"type":"Color","color":4294967296}""" to "Color",
                """{"type":"Color","color":-1}""" to "Color",
                """{"type":"Color","color":2.5}""" to "Color",
                """{"type":"FontWeight","weight":2147483648}""" to "FontWeight",
                """{"type":"FontWeight","weight":0}""" to "FontWeight",
                """{"type":"TextStyle","fontSize":{"type":"Dp","value":8}}""" to "TextStyle",
                """{"type":"TextStyle","color":null}""" to "TextStyle",
                """{"type":"TextStyle","unknown":0}""" to "TextStyle",
                """{"type":"horizontalGradient","colors":[]}""" to "Brush",
                """{"type":"PaddingValues","start":{"type":"Dp","value":-2}}""" to "PaddingValues",
                """{"type":"ThemeColor","name":"notAThemeToken"}""" to "Color",
                """{"type":"Range","start":1.0,"end":0.0}""" to "Range",
            )
        invalid.forEach { (source, family) ->
            assertTrue(
                ValueParser.validate(Json.parseToJsonElement(source), family).isFailure,
                source,
            )
        }
    }

    @Test fun stateIntegersFailBeforeNativeNarrowing() {
        for (value in listOf(-1L, 2147483648L)) {
            val nodes =
                listOf(
                    """"type":"Slider","props":{"steps":$value,
                    "valueRange":{"type":"Range","start":0.0,"end":1.0}}""",
                    """"type":"LazyColumn","props":{"firstVisibleIndex":$value}""",
                )
            nodes.forEach { node ->
                val source = """{"version":"0.1.0","schemaVersion":"1.23.0",
                    "root":{"id":"root",$node}}"""
                assertTrue(IrParser().parse(source).isFailure, source)
            }
        }
    }

    @Test fun taggedValuesRequireTheirSchemaVersionEvenInModifiers() {
        val source = """{"version":"0.1.0","schemaVersion":"1.10.0","root":{
          "id":"root","type":"Text","props":{"text":"Hi","modifier":{"operations":[
            {"type":"size","width":{"type":"Dp","value":8},"height":8}
          ]}}}}"""
        val failure = IrParser().parse(source).exceptionOrNull()
        assertEquals("Value requires newer schema", failure?.message)
    }
}
